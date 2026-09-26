import json
from pathlib import Path
import sys
import tempfile
import unittest

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_research_stdio_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "moex_analyst.mcp_server", "--service", "research", "--workspace", directory])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertIn("save_analysis", names)
                    self.assertIn("calculate_bond", names)
                    data = json.loads((ROOT / "examples/demo-bond.json").read_text())
                    result = await session.call_tool("calculate_bond", {"bond": data})
                    self.assertFalse(result.isError)
                    parsed = result.structuredContent
                    self.assertAlmostEqual(parsed["annual_effective_yield_percent"], 10)
                    bad = await session.call_tool("calculate_bond", {"bond": {"nominal": -1}})
                    self.assertTrue(bad.isError)
                    analysis = json.loads((ROOT / "examples/demo-analysis.json").read_text(encoding="utf-8"))
                    saved = await session.call_tool("save_analysis", {"analysis": analysis, "charts": False})
                    self.assertFalse(saved.isError)
                    self.assertTrue(Path(saved.structuredContent["report"]).is_file())
                    history = await session.call_tool("list_analyses", {})
                    self.assertEqual(len(history.structuredContent["analyses"]), 1)

    async def test_other_services_discover_tools(self):
        for service, expected in [("market", "get_quote"), ("documents", "read_pdf")]:
            params = StdioServerParameters(command=sys.executable,
                args=["-m", "moex_analyst.mcp_server", "--service", service, "--workspace", str(ROOT)])
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    names = {t.name for t in (await session.list_tools()).tools}
                    self.assertIn(expected, names)
