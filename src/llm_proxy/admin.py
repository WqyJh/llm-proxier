import json
import math
from typing import Any

import gradio as gr
from sqlalchemy import func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxy.config import settings
from llm_proxy.database import RequestLog, async_session

PAGE_SIZE = 10


async def get_total_pages(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(RequestLog)
    result = await session.execute(stmt)
    count = result.scalar() or 0
    return math.ceil(count / PAGE_SIZE)


async def fetch_logs(page: int = 1) -> list[RequestLog]:
    offset = (page - 1) * PAGE_SIZE
    async with async_session() as session:
        stmt = (
            select(RequestLog)
            .order_by(desc(RequestLog.timestamp))
            .offset(offset)
            .limit(PAGE_SIZE)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


async def fetch_data(page: int):
    async with async_session() as session:
        total_pages = await get_total_pages(session)
        logs = await fetch_logs(page)
    
    if not logs:
        return [], page, f"Page {page} of {total_pages}"

    # Format data for display. Gradio Dataframe handles list of lists/dicts
    data = []
    for log in logs:
        # Attempt to format response body as JSON if possible for pretty printing
        formatted_response = log.response_body
        try:
            if log.response_body:
                # Sometimes response body is multiple JSONs (event stream)
                # Use a heuristic: if it looks like mulitple lines of "data: ...", keep as is but maybe remove prefix?
                # Task: "对于 event-stream，是多行 json，也要支持收起与展开"
                # So let's try to make it readable.
                pass
        except Exception:
            pass

        data.append([
            log.id,
            log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            log.method,
            log.path,
            log.status_code,
            log.request_body,  # JSON component handles dict
            log.response_body  # JSON component handles string or dict
        ])
    
    return data, page, f"Page {page} of {total_pages}"


def create_admin_interface():
    with gr.Blocks(title="LLM Proxy Admin") as demo:
        gr.Markdown("## Request Logs")
        
        with gr.Row():
            prev_btn = gr.Button("Previous")
            page_state = gr.State(value=1)
            page_label = gr.Label(value="Page 1", show_label=False)
            next_btn = gr.Button("Next")
            refresh_btn = gr.Button("Refresh")
        
        # We use a standard HTML component or iterate to create dynamic expandable rows
        # But Gradio native lists are static.
        # Let's use a customized display using JSON component for detail view? 
        # Or a Dataframe? Dataframe doesn't support expandable JSON cells well.
        # Best approach involves a list of expandable elements, but Gradio construction is static.
        # Alternative: A Dataframe to list summary, and click to view details.
        
        with gr.Row():
            # Summary Table
            log_table = gr.Dataframe(
                headers=["ID", "Timestamp", "Method", "Path", "Status"],
                datatype=["number", "str", "str", "str", "number"],
                interactive=False,
                wrap=True,
                column_widths=["5%", "15%", "10%", "20%", "10%"]
            )
            
            # Detail View
            with gr.Column():
                gr.Markdown("### Details")
                detail_req = gr.JSON(label="Request Body")
                detail_res = gr.Code(label="Response Body", language="json", wrap_lines=True)

        # Hidden state to store full data including bodies
        full_data_state = gr.State([])

        async def update_table(page):
            if page < 1:
                page = 1
            data, current_page, label = await fetch_data(page)
            
            # Prepare summary for table
            table_data = []
            full_data = []
            
            for row in data:
                # row indices: 0:id, 1:ts, 2:meth, 3:path, 4:status, 5:req, 6:res
                table_data.append([row[0], row[1], row[2], row[3], row[4]])
                full_data.append(row)
                
            return table_data, full_data, current_page, label

        async def on_select(evt: gr.SelectData, full_data):
            # evt.index is [row, col]
            row_idx = evt.index[0]
            if row_idx < len(full_data):
                record = full_data[row_idx]
                # record[5] is req, record[6] is res
                return record[5], record[6]
            return None, None

        # Wiring
        refresh_btn.click(update_table, inputs=[page_state], outputs=[log_table, full_data_state, page_state, page_label])
        
        async def go_prev(p):
            return max(1, p - 1)
            
        async def go_next(p):
            return p + 1

        prev_btn.click(go_prev, inputs=[page_state], outputs=[page_state]).then(
            update_table, inputs=[page_state], outputs=[log_table, full_data_state, page_state, page_label]
        )
        
        next_btn.click(go_next, inputs=[page_state], outputs=[page_state]).then(
            update_table, inputs=[page_state], outputs=[log_table, full_data_state, page_state, page_label]
        )
        
        log_table.select(on_select, inputs=[full_data_state], outputs=[detail_req, detail_res])

        # Initial load
        demo.load(update_table, inputs=[page_state], outputs=[log_table, full_data_state, page_state, page_label])

    return demo

# Auth function for Gradio
def auth_check(username, password):
    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD
