from pathlib import Path

from agent_workflow.config import defaults
from agent_workflow.plugin_api import PluginExecutionContext
from agent_workflow_benchmark.benchmarking.service import export_builtin_suite, validate_benchmark
from agent_workflow_benchmark import __version__
from agent_workflow_benchmark.plugin import plugin


def test_descriptor_owns_benchmark_command_and_schemas():
    descriptor = plugin()
    assert descriptor.name == "agent-workflow-benchmark"
    assert __version__ == "0.3.1"
    assert descriptor.version == __version__
    assert [command.name for command in descriptor.commands] == ["benchmark"]
    assert len(descriptor.package_resources) == 21


def test_exported_suite_validates_with_plugin_owned_contracts(tmp_path: Path):
    for benchmark_id in ("priority-picker-v1", "priority-picker-v2", "priority-picker-fast-v1"):
        destination = tmp_path / benchmark_id
        export_builtin_suite(destination, benchmark_id=benchmark_id, force=True)
        value = validate_benchmark(destination / "benchmark-spec.json", None)
        assert value["benchmark_id"] == benchmark_id
