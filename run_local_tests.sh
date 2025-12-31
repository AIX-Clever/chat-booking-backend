#!/bin/bash
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python3 tests/unit/test_fsm_flow.py
