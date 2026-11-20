import yaml
import os

filepath = 'profile/candidate.yaml'

if not os.path.exists(filepath):
    print(f"❌ Ошибка: файл {filepath} не найден. Проверь путь.")
else:
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        print("✅ YAML-файл успешно прочитан и валиден!")
        print("-" * 40)
        print(f"Навыков (skills): {len(data.get('skills', []))}")
        print(f"Задач (tasks): {len(data.get('tasks', []))}")
        print(f"Проектов (projects): {len(data.get('projects', []))}")
        
        print("\nДетализация проектов:")
        for p in data.get('projects', []):
            name = p.get('name', 'Без названия')
            skills_count = len(p.get('skills_used', []))
            tasks_count = len(p.get('tasks_done', []))
            print(f"  - {name}")
            print(f"    skills_used: {skills_count}, tasks_done: {tasks_count}")
            
    except yaml.YAMLError as e:
        print(f"❌ Ошибка синтаксиса YAML (проверь отступы):\n{e}")
    except Exception as e:
        print(f"❌ Неожиданная ошибка:\n{e}")