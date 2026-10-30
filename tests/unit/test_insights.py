from datetime import date

from celerlite.api.insights import pipeline_insights


def test_pipeline_insights_excludes_closed_and_identifies_actionable_deals():
    deals = [
        {'id': 'deal-1', 'name': 'Renewal', 'stage': 'Qualification', 'amount': 100000, 'probability': 40,
         'close_date': '2026-10-20', 'next_step': ''},
        {'id': 'deal-2', 'name': 'Expansion', 'stage': 'Proposal/Price Quote', 'amount': 50000, 'probability': 75,
         'close_date': '2026-11-20', 'next_step': 'Send quote'},
        {'id': 'deal-3', 'name': 'Won', 'stage': 'Closed Won', 'amount': 200000, 'probability': 100,
         'close_date': '2026-10-10', 'next_step': ''},
    ]
    result = pipeline_insights(deals, date(2026, 10, 30))
    assert result['open_deals'] == 2
    assert result['weighted_pipeline'] == 77500
    assert result['overdue_count'] == 1
    assert result['missing_next_step_count'] == 1
    assert [item['id'] for item in result['attention']] == ['deal-1']
