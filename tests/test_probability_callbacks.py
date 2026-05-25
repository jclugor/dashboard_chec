from dash import dcc, html

from chec_dashboard.pages import probability_page



def test_probability_layout_starts_lazy_and_disabled():
    layout = probability_page.get_layout()
    dropdown = None
    for child in layout.children:
        if isinstance(child, html.Div):
            stack = [child]
            while stack:
                current = stack.pop()
                if isinstance(current, dcc.Dropdown) and current.id == "prob-select-criteria":
                    dropdown = current
                    break
                children = getattr(current, "children", None)
                if children is None:
                    continue
                if isinstance(children, list):
                    stack.extend([c for c in children if c is not None])
                else:
                    stack.append(children)
    assert dropdown is not None
    assert dropdown.options == []
    assert dropdown.disabled is True



def test_probability_filter_component_contracts():
    selection_component = probability_page._create_filter_components(
        filter_kind="seleccion",
        value_options=["a", "b"],
        z_index=800,
        component_prefix="prob-select-subcriteria-1",
    )
    assert isinstance(selection_component, list)

    date_component = probability_page._create_filter_components(
        filter_kind="fecha",
        value_options=["2024-01-01", "2024-01-02"],
        z_index=800,
        component_prefix="prob-select-subcriteria-2",
    )
    assert isinstance(date_component, list)

    empty_component = probability_page._create_filter_components(
        filter_kind="seleccion",
        value_options=[],
        z_index=800,
        component_prefix="prob-select-subcriteria-3",
        empty_message="No data",
    )
    assert isinstance(empty_component, html.Div)



def test_probability_graph_component_prefers_data_uri():
    component = probability_page._build_probability_graph_component(
        graph_name="probability_graph_1.png",
        graph_data_uri="data:image/png;base64,ZmFrZQ==",
    )

    assert isinstance(component, html.Div)
    assert component.children[0].src == "data:image/png;base64,ZmFrZQ=="
