import asyncio, ast, json
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path('/Users/imhaneul/Documents/herterarchy/heterarchy-alexandria')
retired={'alexandria_search_skills','alexandria_start_skill_acquisition','alexandria_skill_acquisition_job_status','alexandria_vault_review_queue','alexandria_vault_review_move_plan','alexandria_vault_review_apply_moves'}
expected=set()
for path in (ROOT/'backend/app/mcp_server/tools').rglob('*.py'):
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
            for d in node.decorator_list:
                if isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='tool':
                    for kw in d.keywords:
                        if kw.arg=='name' and isinstance(kw.value,ast.Constant): expected.add(kw.value.value)

async def main():
    params=StdioServerParameters(command='docker',args=['exec','-i','alexandria-backend','/app/.venv/bin/heterarchy-alexandria','mcp','serve','--transport','stdio'])
    async with stdio_client(params) as (read,write):
        async with ClientSession(read,write,read_timeout_seconds=60.0) as session:
            await session.initialize()
            listing=await session.list_tools()
            names={tool.name for tool in listing.tools}
            assert len(names)==46 and names==expected,(len(names),names^expected)
            assert retired.isdisjoint(names)
            create=next(tool for tool in listing.tools if tool.name=='alexandria_create_note')
            assert 'librarian' not in json.dumps(create.input_schema).lower()
            status=await session.call_tool('alexandria_get_graph_projection_status',{})
            assert not status.is_error,status
            steward=await session.call_tool('alexandria_memory_steward_readiness',{'project':'heterarchy-alexandria','max_compact_age_days':30})
            assert not steward.is_error,steward
            graph_result=status.structured_content["result"]
            steward_result=steward.structured_content["result"]
            assert graph_result["status"]=="ready" and graph_result["graph_read_model"]=="postgresql" and graph_result["errors"]==[]
            assert steward_result["ready"] is True and steward_result["warnings"]==[]
            report={'transport':'stdio in deployed container -> live HTTP backend','tool_count':len(names),'exact_source_match':True,'retired_absent':True,'create_note_librarian_absent':True,'graph':status.model_dump(mode='json'),'memory_steward':steward.model_dump(mode='json')}
            print(json.dumps(report,indent=2))

asyncio.run(main())
