"""Explainable pipeline signals derived from current CRM records."""

from datetime import date


def pipeline_insights(deals: list[dict], today: date | None = None) -> dict:
    today = today or date.today()
    open_deals = [deal for deal in deals if deal.get('stage') not in ('Closed Won', 'Closed Lost')]
    weighted = sum(max(0, int(deal.get('amount') or 0)) *
                   min(100, max(0, int(deal.get('probability') or 0))) / 100 for deal in open_deals)
    overdue = []
    missing_next_step = []
    for deal in open_deals:
        try:
            if date.fromisoformat(str(deal.get('close_date') or '')) < today:
                overdue.append(deal)
        except ValueError:
            pass
        if not str(deal.get('next_step') or '').strip():
            missing_next_step.append(deal)
    return {
        'open_deals': len(open_deals),
        'weighted_pipeline': round(weighted),
        'overdue_count': len(overdue),
        'missing_next_step_count': len(missing_next_step),
        'attention': [
            {'id': deal['id'], 'name': deal.get('name', 'Opportunity'),
             'account_name': deal.get('account_name', ''),
             'reason': 'Past target close date' if deal in overdue else 'Missing next step',
             'amount': deal.get('amount', 0)}
            for deal in sorted({d['id']: d for d in overdue + missing_next_step}.values(),
                               key=lambda item: int(item.get('amount') or 0), reverse=True)[:6]
        ],
        'signals': [
            {'kind': 'overdue', 'count': len(overdue), 'message': 'Open deals past their target close date'},
            {'kind': 'next_step', 'count': len(missing_next_step), 'message': 'Open deals without a next step'},
        ],
    }
