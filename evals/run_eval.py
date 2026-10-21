import json
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

API_URL = "http://127.0.0.1:8000/classify"
CASES_FILE = Path(__file__).with_name("cases.json")
FIELDS = ("category", "priority", "needs_human")


def main():
    cases = json.loads(CASES_FILE.read_text(encoding="utf-8"))
    total_fields = len(cases) * len(FIELDS)
    correct_fields = 0
    passed_cases = 0

    print(f"Evaluating {len(cases)} cases against {API_URL}\n")

    for index, case in enumerate(cases, start=1):
        payload = json.dumps(
            {"message": case["message"]}
        ).encode("utf-8")

        request = Request(
            API_URL,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urlopen(request, timeout=90) as response:
                actual = json.loads(response.read().decode("utf-8"))
        except (HTTPError, URLError, TimeoutError) as exc:
            print(f"Case {index}: REQUEST FAILED - {exc}")
            sys.exit(1)

        expected = case["expected"]
        matches = [
            field
            for field in FIELDS
            if actual.get(field) == expected.get(field)
        ]

        correct_fields += len(matches)
        case_passed = len(matches) == len(FIELDS)
        passed_cases += int(case_passed)

        result = "PASS" if case_passed else "FAIL"
        print(f"Case {index}: {result} ({len(matches)}/{len(FIELDS)} fields)")

        if not case_passed:
            for field in FIELDS:
                if actual.get(field) != expected.get(field):
                    print(
                        f"  {field}: expected={expected.get(field)!r}, "
                        f"actual={actual.get(field)!r}"
                    )

    print("\n--- Evaluation Summary ---")
    print(f"Cases fully matched: {passed_cases}/{len(cases)}")
    print(
        f"Field accuracy: {correct_fields}/{total_fields} "
        f"({correct_fields / total_fields * 100:.1f}%)"
    )


if __name__ == "__main__":
    main()