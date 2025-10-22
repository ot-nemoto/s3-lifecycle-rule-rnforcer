#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Tuple

import boto3
import botocore

RULE_ID_PREFIX = "abort-multipart-after-{}-days"


def is_global_abort_rule(rule: Dict[str, Any], max_days: int) -> bool:
    """グローバル対象の中止ルールを検出"""
    if rule.get("Status") != "Enabled":
        return False
    if "AbortIncompleteMultipartUpload" not in rule:
        return False
    days = rule["AbortIncompleteMultipartUpload"].get("DaysAfterInitiation")
    if days is None or int(days) > int(max_days):
        return False
    f = rule.get("Filter")
    if "Prefix" in rule and rule.get("Prefix", "") == "":
        return True
    if f is None or (isinstance(f, dict) and len(f) == 0):
        return True
    if isinstance(f, dict) and "And" in f and not f["And"]:
        return True
    return False


def upsert_rule(
    rules: List[Dict[str, Any]], days: int
) -> Tuple[List[Dict[str, Any]], bool]:
    """必要なら全体適用の中止ルールを追加/更新"""
    target_id = RULE_ID_PREFIX.format(days)
    new_rule = {
        "ID": target_id,
        "Status": "Enabled",
        "Filter": {},
        "AbortIncompleteMultipartUpload": {"DaysAfterInitiation": int(days)},
    }

    for r in rules:
        if is_global_abort_rule(r, days):
            return rules, False

    for i, r in enumerate(rules):
        if r.get("ID") == target_id:
            if r != new_rule:
                rules[i] = new_rule
                return rules, True
            return rules, False

    rules.append(new_rule)
    return rules, True


def dump_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=False)


def save_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def load_bucket_list(args) -> List[str]:
    buckets: List[str] = []
    if args.buckets:
        buckets.extend([b.strip() for b in args.buckets if b.strip()])
    if args.bucket_file:
        with open(args.bucket_file, "r", encoding="utf-8") as f:
            for line in f:
                name = line.strip()
                if name and not name.startswith("#"):
                    buckets.append(name)
    return list(dict.fromkeys(buckets))  # 重複排除


def main():
    parser = argparse.ArgumentParser(
        description="Ensure S3 buckets have a lifecycle rule to abort incomplete multipart uploads."
    )
    parser.add_argument("--days", type=int, default=7, help="中止までの日数（既定: 7）")
    parser.add_argument("--profile", default=None, help="AWS CLI プロファイル名")
    parser.add_argument(
        "--apply", action="store_true", help="実際に適用（省略時は提案のみ）"
    )
    parser.add_argument("--suggest", action="store_true", help="提案のみ（明示）")
    parser.add_argument(
        "--print-rules",
        action="store_true",
        help="各バケットの現在のライフサイクルルールを表示",
    )
    parser.add_argument(
        "--print-proposed", action="store_true", help="提案（適用後）ルールを表示"
    )
    parser.add_argument(
        "--export-dir", default=None, help="ルールをファイル出力するディレクトリ"
    )
    # ★ 修正箇所：空白区切り複数指定に対応
    parser.add_argument(
        "--buckets", nargs="+", help="空白区切りで複数のバケット名を指定"
    )
    parser.add_argument("--bucket-file", help="1行1バケット名のファイルパス")

    args = parser.parse_args()
    dry_run = not args.apply

    buckets = load_bucket_list(args)
    if not buckets:
        print(
            "[ERROR] 対象バケットが指定されていません。--buckets または --bucket-file を指定してください。",
            file=sys.stderr,
        )
        sys.exit(1)

    session_kwargs = {}
    if args.profile:
        session_kwargs["profile_name"] = args.profile
    session = boto3.Session(**session_kwargs)
    s3 = session.client("s3")

    summary = {"ok": [], "would_change": [], "changed": [], "skipped": [], "errors": []}

    for bucket in buckets:
        try:
            # バケット存在確認
            try:
                s3.get_bucket_location(Bucket=bucket)
            except botocore.exceptions.ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("NoSuchBucket", "AccessDenied"):
                    summary["skipped"].append((bucket, code))
                    print(f"[SKIP] {bucket}: {code}")
                    continue
                raise

            # 現在のライフサイクル取得
            try:
                resp = s3.get_bucket_lifecycle_configuration(Bucket=bucket)
                current_rules = resp.get("Rules", [])
            except botocore.exceptions.ClientError as e:
                if (
                    e.response.get("Error", {}).get("Code")
                    == "NoSuchLifecycleConfiguration"
                ):
                    current_rules = []
                else:
                    raise

            proposed_rules, will_change = upsert_rule(current_rules[:], args.days)

            # ルール出力
            if args.print_rules:
                print(f"\n--- {bucket} : CURRENT RULES ---")
                print(dump_json({"Rules": current_rules}))
                if args.export_dir:
                    save_file(
                        os.path.join(args.export_dir, f"{bucket}.current.json"),
                        dump_json({"Rules": current_rules}),
                    )
            if args.print_proposed:
                print(f"\n--- {bucket} : PROPOSED RULES ---")
                print(dump_json({"Rules": proposed_rules}))
                if args.export_dir:
                    save_file(
                        os.path.join(args.export_dir, f"{bucket}.proposed.json"),
                        dump_json({"Rules": proposed_rules}),
                    )

            # 判定・適用
            if not will_change:
                summary["ok"].append(bucket)
                print(f"[OK]   {bucket}: 既に適切な中止ルールあり（≦{args.days}日）")
            else:
                if dry_run:
                    summary["would_change"].append(bucket)
                    print(f"[SUGGEST] {bucket}: 中止ルールを追加/更新すべき")
                else:
                    s3.put_bucket_lifecycle_configuration(
                        Bucket=bucket, LifecycleConfiguration={"Rules": proposed_rules}
                    )
                    summary["changed"].append(bucket)
                    print(
                        f"[APPLY] {bucket}: 中止ルールを設定しました（{args.days}日）"
                    )

        except Exception as e:
            summary["errors"].append((bucket, str(e)))
            print(f"[ERROR] {bucket}: {e}", file=sys.stderr)

    # --- Summary ---
    print("\n=== Summary ===")
    print(f"  OK（すでに適切）     : {len(summary['ok'])}")
    print(f"  提案（変更候補）    : {len(summary['would_change'])}")
    print(f"  適用済              : {len(summary['changed'])}")
    print(f"  スキップ            : {len(summary['skipped'])}")
    print(f"  エラー              : {len(summary['errors'])}")

    if summary["would_change"]:
        print("\n変更提案バケット:")
        for b in summary["would_change"]:
            print(f" - {b}")
    if summary["errors"]:
        print("\nエラー:")
        for b, m in summary["errors"]:
            print(f" - {b}: {m}")


if __name__ == "__main__":
    main()
