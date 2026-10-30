from typing import Any


def run_graph_with_trace(graph: Any, graph_input: Any, graph_config: dict) -> tuple[dict, list[str]]:
    """Run one graph request and collect the top-level nodes that actually ran."""
    graph_nodes: list[str] = []
    for update in graph.stream(graph_input, config=graph_config, stream_mode="updates"):
        for node_name in update:
            if node_name != "__interrupt__":
                graph_nodes.append(node_name)

    snapshot = graph.get_state(graph_config)
    interrupted_tasks = [task for task in snapshot.tasks if task.interrupts]
    for task in interrupted_tasks:
        if task.name and (not graph_nodes or graph_nodes[-1] != task.name):
            graph_nodes.append(task.name)

    graph_answer = dict(snapshot.values)
    if interrupted_tasks:
        graph_answer["__interrupt__"] = True
    return graph_answer, graph_nodes
