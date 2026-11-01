"""Each page must load without an exception. Run after `python run_all.py`."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("page", ["app/dashboard.py", "app/pages/1_Hotspot_Map.py",
                                  "app/pages/2_Forecast.py"])
def test_page_runs(page):
    app = AppTest.from_file(str(ROOT / page), default_timeout=170).run()
    assert not app.exception, [e.value for e in app.exception]


def test_recommendation_changes_with_inputs():
    app = AppTest.from_file(str(ROOT / "app/dashboard.py"), default_timeout=170).run()
    assert any("class='act'" in m.value for m in app.markdown)
    app.sidebar.selectbox[1].set_value("Ground chicken")
    app.sidebar.selectbox[2].select_index(3)
    app.sidebar.checkbox[0].set_value(True)
    app.run()
    assert not app.exception
    assert any("Redirect to cooked line" in m.value for m in app.markdown)


def test_self_check_block_renders():
    app = AppTest.from_file(str(ROOT / "app/dashboard.py"), default_timeout=170).run()
    app.number_input(key="plant_samples").set_value(40)
    app.number_input(key="plant_positives").set_value(11)
    app.run()
    assert not app.exception
    assert any("Not an FSIS determination" in c.value for c in app.caption)
    labels = [m.label for m in app.metric]
    assert len(labels) > 3
