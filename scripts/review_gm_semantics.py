"""Print the numerical approval-gate audit as JSON."""
import json

from fet_analyzer.analysis.gm_review import review_gm_semantics


if __name__ == "__main__":
    print(json.dumps(review_gm_semantics(), indent=2))
