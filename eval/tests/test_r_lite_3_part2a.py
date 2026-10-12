from eval.rag.r_lite_3_part2a import stop_reasons


def test_owner_gate_refuses_real_table_loss_even_when_recall_passes():
    assert 'REAL_TABLE_RETYPED' in stop_reasons(20,['real-table'],[],0,0)


def test_owner_gate_threshold_is_eighteen_and_target_breakage_stops():
    assert stop_reasons(18,[],[],0,0)==[]
    assert 'WEF_CHART_CHECK_BELOW_18_OF_20' in stop_reasons(17,[],[],0,0)
    assert 'FROZEN_T2_OR_T3' in stop_reasons(20,[],[],1,0)
    assert 'FROZEN_T2_OR_T3' in stop_reasons(20,[],[],0,1)
