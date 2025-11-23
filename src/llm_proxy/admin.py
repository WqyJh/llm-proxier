import json
import math

import gradio as gr
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from llm_proxy.config import settings
from llm_proxy.database import RequestLog, async_session

PAGE_SIZE = 10


def parse_streaming_response(response_body: str | None) -> list[dict] | None:  # noqa: PLR0911
    """
    只解析严格符合 SSE 流格式的响应:
      data: <json>\\n\\n
    最后一行可能是: data: [DONE]

    其它格式(普通 JSON,HTML 等)一律返回 None,表示"不要当流式 JSON 解析",
    由上层直接按字符串展示(用 gr.Code)。
    """
    if response_body is None:
        return None
    if not isinstance(response_body, str):
        return None

    # 必须是以 data: 开头且包含空行分隔的多段
    if not (response_body.startswith("data: ") and "\n\n" in response_body):
        return None

    lines = response_body.split("\n\n")
    chunks: list[dict] = []
    for line in lines:
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if not stripped_line.startswith("data: "):
            # 只要有一行不是 data: 开头,就认为整体不是规范流式格式
            return None
        json_str = stripped_line[6:].strip()
        if json_str == "[DONE]":
            continue
        try:
            chunk = json.loads(json_str)
        except json.JSONDecodeError:
            # 任意一块解析失败,则整体放弃解析
            return None
        # 只接受对象/数组,标量也不当流式 JSON 处理
        if not isinstance(chunk, dict | list):
            return None
        chunks.append(chunk)

    return chunks or None


async def get_total_pages(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(RequestLog)
    result = await session.execute(stmt)
    count = result.scalar() or 0
    return math.ceil(count / PAGE_SIZE)


async def fetch_logs(page: int = 1) -> list[RequestLog]:
    offset = (page - 1) * PAGE_SIZE
    async with async_session() as session:
        stmt = select(RequestLog).order_by(desc(RequestLog.timestamp)).offset(offset).limit(PAGE_SIZE)
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
        # 原样存储 response_body,解析逻辑在前端 on_select 里做
        data.append(
            [
                log.id,
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                log.method,
                log.path,
                log.status_code,
                log.fail,
                log.request_body,  # JSON component handles dict
                log.response_body,  # raw string (可能是 stream / json / html)
            ]
        )

    return data, page, f"Page {page} of {total_pages}"


def create_admin_interface():  # noqa: PLR0915
    theme = gr.themes.Soft(
        primary_hue="indigo",
        secondary_hue="slate",
        neutral_hue="slate",
        font=[
            gr.themes.GoogleFont("Inter"),
            "ui-sans-serif",
            "system-ui",
            "sans-serif",
        ],
    )

    with gr.Blocks(
        theme=theme,
        title="LLM Proxy Admin",
        head='<link rel="icon" type="image/svg+xml" href="/assets/icon.svg">',
        css="""
#page-controls-row.row.unequal-height {
    /* 强制这一行的所有子元素等高(与按钮同高) */
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
""",
    ) as demo:
        with gr.Row(elem_classes="header-container"):
            gr.HTML(
                """
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
            """
            )

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
            # 流式 JSON 结果(data: <json>\n\n)在这里用 JSON 展示
            detail_res_stream = gr.JSON(label="Response Body", visible=False)
            # 非流式 / HTML / 其它文本在这里原样展示
            detail_res_raw = gr.Code(label="Response Body", language="json", visible=False, wrap_lines=True)

        # Hidden state to store full data including bodies
        full_data_state = gr.State([])

        async def update_table(page):
            page = max(page, 1)
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
            if row_idx < 0 or row_idx >= len(full_data):
                return (
                    {},
                    gr.update(value=None, visible=False),
                    gr.update(value="", visible=False),
                )

            record = full_data[row_idx]
            req_val = record[6] if record[6] is not None else {}
            resp_body = record[7]

            # 1. 优先判断是否为流式 SSE: data: <json>\n\n
            parsed_chunks = parse_streaming_response(resp_body)
            if parsed_chunks is not None:
                # 流式 JSON chunk 列表,用 JSON 展示
                return (
                    req_val,
                    gr.update(value=parsed_chunks, visible=True),
                    gr.update(value="", visible=False),
                )

            # 2. 非流式: 尝试当普通 JSON 解析(dict / list)
            json_val = None
            if isinstance(resp_body, dict | list):
                json_val = resp_body
            elif isinstance(resp_body, str):
                try:
                    loaded = json.loads(resp_body)
                    if isinstance(loaded, dict | list):
                        json_val = loaded
                except json.JSONDecodeError:
                    json_val = None

            if json_val is not None:
                # 普通 JSON,用 JSON 组件展示
                return (
                    req_val,
                    gr.update(value=json_val, visible=True),
                    gr.update(value="", visible=False),
                )

            # 3. 剩下的当纯文本 / HTML 展示
            text = "" if resp_body is None else str(resp_body)
            return (
                req_val,
                gr.update(value=None, visible=False),
                gr.update(value=text, visible=True),
            )

        # Wiring
        refresh_btn.click(
            update_table,
            inputs=[page_state],
            outputs=[log_table, full_data_state, page_state, page_label],
        )

        async def go_prev(p):
            return max(1, p - 1)

        async def go_next(p):
            return p + 1

        prev_btn.click(go_prev, inputs=[page_state], outputs=[page_state]).then(
            update_table,
            inputs=[page_state],
            outputs=[log_table, full_data_state, page_state, page_label],
        )

        next_btn.click(go_next, inputs=[page_state], outputs=[page_state]).then(
            update_table,
            inputs=[page_state],
            outputs=[log_table, full_data_state, page_state, page_label],
        )

        log_table.select(
            on_select,
            inputs=[full_data_state],
            outputs=[detail_req, detail_res_stream, detail_res_raw],
        )

        # Initial load
        demo.load(
            update_table,
            inputs=[page_state],
            outputs=[log_table, full_data_state, page_state, page_label],
        )

    return demo


# Auth function for Gradio
def auth_check(username, password):
    return username == settings.ADMIN_USERNAME and password == settings.ADMIN_PASSWORD
