# Kiro files

Work done in Kiro (Kiro Pro, about 27 credits):

- `hooks/pytest-on-save.json`: created by the Kiro agent. It runs the tests when a Python file is saved.
- `specs/plant-self-check/`: created with Kiro Quick Spec. Kiro wrote the requirements, design and
  tasks, then wrote the engine code in `src/decision/actions.py`, the Section 1 block and sidebar
  inputs in `app/dashboard.py`, and the tests in `tests/test_decision.py`.

Drafted with an AI coding assistant from work already in this repo, not in Kiro:

- `steering/` files.
- `specs/category-exposure/`, which records that work after the fact.

Manual changes and review:

- Muhammad Waqar Saleem asked an AI coding assistant to do the Kiro work. It operated the Kiro window,
  wrote the prompts, chose the spec options and reviewed the diffs.
- One Kiro rewrite of `actions.py` by a PowerShell command was denied, to protect file encoding.
- Optional property tests in the Kiro task list were skipped, except 1.2. Tasks left unchecked are optional.
- `test_self_check_block_renders` in `tests/test_app.py` was added with an AI coding assistant.
- An AI coding assistant added the rule that worse own samples raise the risk level one step, with a test.

Not built in Kiro: the `web/` app and the published-category test were built with an AI coding assistant.
