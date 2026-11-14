"""Offline common input publisher/query CLI; does not alter any screening service."""

from __future__ import annotations

import argparse
import json

from sec_xbrl.screening.market_input_publication import (
    MarketInputAssessmentReader,
    MarketInputReader,
    publish_market_input_assessment,
    publish_market_inputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    publish = commands.add_parser("publish")
    publish.add_argument("--config", required=True)
    publish.add_argument("--config-sha256", required=True)
    publish.add_argument("--output", required=True)
    query = commands.add_parser("query")
    query.add_argument("--manifest", required=True)
    query.add_argument("--sha256", required=True)
    query.add_argument("--cik", required=True)
    query.add_argument("--input-id")
    assess = commands.add_parser("assess")
    assess.add_argument("--parent", required=True)
    assess.add_argument("--parent-sha256", required=True)
    assess.add_argument("--output", required=True)
    assessment_query = commands.add_parser("assessment-query")
    assessment_query.add_argument("--manifest", required=True)
    assessment_query.add_argument("--sha256", required=True)
    assessment_query.add_argument("--cik", required=True)
    assessment_query.add_argument("--input-id")
    args = parser.parse_args()
    if args.command == "publish":
        result = publish_market_inputs(args.config, args.config_sha256, args.output)
    elif args.command == "assess":
        result = publish_market_input_assessment(
            {"path": args.parent, "sha256": args.parent_sha256}, args.output
        )
    elif args.command == "assessment-query":
        result = MarketInputAssessmentReader(args.manifest, args.sha256).query(
            args.cik, args.input_id
        )
    else:
        result = MarketInputReader(args.manifest, args.sha256).query(args.cik, args.input_id)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
