"""Offline demonstration: python -m backend.app.engine --dataset PATH."""
import argparse
import json
from . import analyze, load_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--employees', nargs='+', default=['E0001', 'E0002', 'E0003'])
    args = parser.parse_args()
    data = load_dataset(args.dataset)
    report = []
    for identifier in args.employees:
        employee = next((x for x in data['employees'] if x['employee_id'] == identifier), None)
        if employee is None:
            parser.error(f'Unknown employee: {identifier}')
        result = analyze(employee, data['history'], data['events'], data['catalog'], data['as_of_date'])
        report.append({key: result[key] for key in ('employee_id', 'current_role', 'current_grade',
                       'target', 'next_grade_target', 'recommendations', 'no_recommendation_reason', 'warnings')})
    print(json.dumps(report, ensure_ascii=True, indent=2))


if __name__ == '__main__':
    main()
