"""Офлайн-пример двух стадий обработки сообщений."""
from app.scoring.dedup import text_hash
from app.scoring.keyword_filter import keyword_prefilter


def main():
    messages = [
        "Я владелец мастерской, рост остановился. Как масштабировать продажи?",
        "Я владелец мастерской, рост остановился! Как масштабировать продажи?",
        "Предлагаю свои услуги по ремонту мебели.",
    ]
    seen = set()
    for message in messages:
        fingerprint = text_hash(message)
        if fingerprint in seen:
            status = "повтор сообщения"
        else:
            seen.add(fingerprint)
            should_score, reason = keyword_prefilter(message)
            status = "передать на оценку модели" if should_score else "остановить до модели"
            status += f" ({reason})"
        print(f"{status}\n  {message}")


if __name__ == "__main__":
    main()
