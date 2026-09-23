"""Skill coverage is not a promotion probability."""

def readiness(levels, target):
    required = target["required_skills"]
    total = sum(required.values())
    return round(100 * sum(min(levels.get(key, 0), value)
                           for key, value in required.items()) / total, 2) if total else 100.0


def gaps_for(levels, target, catalog):
    names = {item['skill_id']: item['name'] for item in catalog['skills']}
    return [{'skill_id': key, 'name': names[key], 'current': levels.get(key, 0),
             'required': value, 'gap': value - levels.get(key, 0),
             'critical': key in target['critical_skills']}
            for key, value in target['required_skills'].items() if levels.get(key, 0) < value]


def next_grade_target(employee, catalog):
    grades = ('Junior', 'Middle', 'Senior', 'Lead')
    index = grades.index(employee['grade'])
    if index == len(grades) - 1:
        return None
    return next((item for item in catalog['role_profiles']
                 if item['role'] == employee['role'] and item['grade'] == grades[index + 1]), None)
