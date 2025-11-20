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
            log.fail,
            log.request_body,  # JSON component handles dict
            log.response_body  # JSON component handles string or dict
        ])
    
    return data, page, f"Page {page} of {total_pages}"


def create_admin_interface():
    theme = gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="slate",
        neutral_hue="slate",
        font=[gr.themes.GoogleFont("Inter"), "ui-sans-serif", "system-ui", "sans-serif"]
    )

    with gr.Blocks(
        theme=theme,
        title="LLM Proxy Admin",
        head='<link rel="icon" type="image/svg+xml" href="/assets/icon.svg">',
        css="""
#page-controls-row.row.unequal-height {
    /* 强制这一行的所有子元素等高（与按钮同高） */
    align-items: stretch !important;
}

/* 确保页码这个块本身参与等高布局并内部用 flex 居中 */
#page-label.block {
    display: flex !important;
    align-items: center;
    justify-content: center;
    text-align: center;
}

.header-container {
    display: flex;
    align-items: center;
    margin-bottom: 20px;
}
.app-logo {
    margin-right: 12px;
}
"""
    ) as demo:
        with gr.Row(elem_classes="header-container"):
            gr.HTML("""
                <div style="display: flex; align-items: center;">
                    <div class="app-logo">
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="40" height="40" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                          <defs>
                            <linearGradient id="grad1" x1="0%" y1="0%" x2="100%" y2="100%">
                              <stop offset="0%" style="stop-color:#6366f1;stop-opacity:1" />
                              <stop offset="100%" style="stop-color:#8b5cf6;stop-opacity:1" />
                            </linearGradient>
                          </defs>
                          <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="url(#grad1)" fill="none"/>
                        </svg>
                    </div>
                    <h1 style="margin: 0; font-size: 24px; font-weight: 600; background: linear-gradient(to right, #6366f1, #8b5cf6); -webkit-background-clip: text; -webkit-text-fill-color: transparent;">LLM Proxy Admin</h1>
                </div>
            """)

        gr.Markdown("### Request Logs")

        with gr.Row(elem_id="page-controls-row"):
            prev_btn = gr.Button("Previous")
            page_state = gr.State(value=1)
            page_label = gr.Markdown("Page 1", elem_id="page-label")
            next_btn = gr.Button("Next")
            refresh_btn = gr.Button("Refresh")

        with gr.Column():
            # Summary Table
            log_table = gr.Dataframe(
                headers=["ID", "Timestamp", "Method", "Path", "Status", "Fail"],
                datatype=["number", "str", "str", "str", "number", "str"],
                interactive=False,
                wrap=True,
                column_widths=["5%", "15%", "10%", "20%", "10%", "5%"],
            )

            # Detail View
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
                fail_display = "🔴" if row[5] == 1 else ""
                table_data.append([row[0], row[1], row[2], row[3], row[4], fail_display])
                full_data.append(row)

            return table_data, full_data, current_page, label

        async def on_select(evt: gr.SelectData, full_data):
            row_idx = evt.index[0]
            if row_idx < len(full_data):
                record = full_data[row_idx]
                return record[6], record[7]
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
