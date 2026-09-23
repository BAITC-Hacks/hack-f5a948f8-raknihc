"""Deterministic explanations and counterfactual comparisons only."""


def explain(item):
    facts = item['facts']
    changes = '; '.join(f"{x['skill_id']}: {x['before']} → {x['after']}, требуется {x['required']}"
                        + (' (критический)' if x['critical'] else '')
                        for x in (facts['skill_changes'] or facts['next_grade_changes']))
    return (f"Текущий профиль: {facts['current_role']} / {facts['current_grade']}. "
            f"Цель: {facts['target_role']} / {facts['target_grade']}. {changes}. "
            f"Похожих записей среди последних 30: {facts['similar_history_count']}; "
            f"завершено {facts['similar_completed']}, пропущено/отклонено/прекращено "
            f"{facts['similar_negative']}. Соответствие требованиям: "
            f"{item['readiness_before']}% → {item['readiness_after']}%. "
            f"Трудозатраты: {item['duration_hours']} ч.")


def counterfactual(best, alternative):
    if alternative is None:
        return {'alternative_event_id': None, 'why_this': explain(best),
                'why_not': 'Другой допустимой активности, сокращающей целевой дефицит, нет.'}
    deltas = {key: round(best['score_breakdown'][key] - alternative['score_breakdown'][key], 6)
              for key in best['score_breakdown'] if key != 'final_score'}
    if best['score'] != alternative['score']:
        reason = (f"Score {best['score']} против {alternative['score']}; "
                  f"разница компонентов (выбранная − альтернатива): {deltas}.")
    elif best['duration_hours'] != alternative['duration_hours']:
        reason = f"Score одинаков; меньше трудозатраты: {best['duration_hours']} против {alternative['duration_hours']} ч."
    else:
        reason = 'Score и трудозатраты одинаковы; порядок по event_id. Преимущество по качеству не установлено.'
    return {'alternative_event_id': alternative['event_id'], 'why_this': explain(best),
            'why_not': reason, 'score_margin': round(best['score'] - alternative['score'], 6),
            'component_deltas': deltas,
            'alternative_readiness_after': alternative['readiness_after']}


def card_options(best, alternative):
    """Grounded wording variants; the LLM may edit presentation, never facts."""
    facts = best['facts']
    changes = facts['skill_changes'] or facts['next_grade_changes']
    skills = '; '.join(f"{x['skill_id']}: {x['before']} → {x['after']} / {x['required']}"
                       for x in changes[:3])
    b = best['score_breakdown']
    why = (f"{skills}. Критический вклад: {b['critical_gap_impact']}; "
           f"поправка истории: {b['history_modifier']}.")
    if alternative:
        comparison = counterfactual(best, alternative)
        differences = ', '.join(f'{key} {value:+g}' for key, value in comparison['component_deltas'].items() if value)
        why_not = (f"{alternative['event_id']}: score {alternative['score']} против {best['score']}. "
                   f"Разница: {differences}.") if differences else comparison['why_not']
    else:
        why_not = 'Других допустимых кандидатов нет.'
    impact = f"Соответствие цели {facts['target_role']} / {facts['target_grade']}: {best['readiness_before']}% → {best['readiness_after']}%."
    history = best['factors']['participation']
    caution = ('Есть пропуски/отказы похожих активностей; стоит уточнить удобный формат.' if history['negative']
               else 'Нет истории похожих активностей; предпочтения пока неизвестны.' if not history['count']
               else 'Рост навыков рассчитан по правилам датасета и не гарантирует повышения.')
    return {
        'explanation': [f"Следующий шаг: {best['title']}.", f"Рекомендуется {best['title']} для развития навыков."],
        'why_this': [why, 'Основание выбора: ' + why],
        'why_not': [why_not, 'Сравнение с альтернативой: ' + why_not],
        'expected_career_impact': [impact, 'После выполнения: ' + impact],
        'caution': [caution, 'Учтите: ' + caution]}


def deterministic_card(best, alternative=None, reason='disabled'):
    return {'source': 'deterministic', 'fallback_reason': reason,
            **{key: variants[0] for key, variants in card_options(best, alternative).items()}}
