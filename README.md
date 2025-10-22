# S3 Lifecycle Rule Enforcer

Amazon S3 バケットに対して、
**「未完了のマルチパートアップロードを 7 日後に自動中止するライフサイクルルール」**
を一括でチェック・提案・適用するためのツールです。

Trusted Advisor のコスト最適化チェック（`S3 で未完了のマルチパートアップロードを中止していない`）に対応する運用支援スクリプトです。

---

## 📌 機能

- 指定した複数の S3 バケットに対し、ライフサイクルルールをチェック
- 未完了マルチパートアップロードを **N 日後に中止** するルールを自動的に

  - 存在チェック
  - 提案
  - 追記または更新

- バケットごとの

  - **現在のルール**
  - **提案（適用後）のルール**
    の表示／JSON ファイル出力に対応

- `--apply` オプションにより一括適用可能
- 既に同等のルールが存在する場合はスキップ
- 既存の他ルールを壊さずに追記・更新

---

## 🧰 必要環境

- Python 3.8 以上
- AWS CLI 認証済みの環境（`~/.aws/credentials` 等）
- `boto3` ライブラリ

### インストール

```bash
pip install boto3
```

---

## 🚀 使い方

### 1. ドライラン（提案のみ）

```bash
python ensure_abort_multipart.py --profile my-aws --buckets example-bucket-1 example-bucket-2
```

または

```bash
python ensure_abort_multipart.py --profile my-aws --bucket-file buckets.txt
```

- 実際には S3 へ変更を加えず、変更が必要なバケットを表示します。

---

### 2. 実際にルールを適用

```bash
python ensure_abort_multipart.py --profile my-aws --apply --buckets example-bucket-1
```

- ライフサイクルルールが存在しない、または不適切なバケットに対して
  `abort-multipart-after-7-days` というルールを追加または更新します。

---

### 3. 日数を変更する場合

```bash
python ensure_abort_multipart.py --profile my-aws --apply --days 5 --buckets example-bucket-1
```

- Trusted Advisor の推奨は 7 日ですが、環境に合わせて短縮可能です。

---

### 4. 現在と提案のルールを表示する

```bash
python ensure_abort_multipart.py --print-rules --print-proposed --bucket-file buckets.txt
```

- 現在のライフサイクルルールと提案後の内容を JSON 形式で標準出力に表示します。

---

### 5. ルールをファイルに出力する

```bash
python ensure_abort_multipart.py --print-rules --print-proposed --export-dir out/ --bucket-file buckets.txt
```

- `out/` 以下に以下のようなファイルが出力されます：

  - `<bucket>.current.json`：現在のルール
  - `<bucket>.proposed.json`：提案後のルール

---

## 📝 オプション一覧

| オプション           | 説明                                                 |
| -------------------- | ---------------------------------------------------- |
| `--profile`          | 使用する AWS CLI プロファイル名                      |
| `--days`             | 中止までの日数（デフォルト: 7 日）                   |
| `--apply`            | 実際に S3 バケットへライフサイクルルールを適用する   |
| `--suggest`          | 提案のみ（明示）。`--apply` を付けない場合と同じ挙動 |
| `--print-rules`      | 現在のライフサイクルルールを JSON 形式で表示         |
| `--print-proposed`   | 提案（適用後）のルールを JSON 形式で表示             |
| `--export-dir <dir>` | ルールをファイルとして出力するディレクトリ           |
| `--buckets`          | 空白区切りで複数のバケット名を指定                   |
| `--bucket-file`      | 1行1バケット名のファイルパス                         |

---

## 🧭 処理の流れ

1. 対象バケットを取得（`--buckets` または `--bucket-file` で指定）
2. 各バケットに対し `GetBucketLifecycleConfiguration` を実行
3. 全オブジェクト対象かつ `DaysAfterInitiation <= N` の中止ルールがあるかチェック
4. 無ければ提案／または `PutBucketLifecycleConfiguration` で追記
5. 変更のサマリを出力

---

## 🛡️ IAM 必要権限

最小権限ポリシーの例：

```json
{
  "Version": "2012-10-17",
  "Statement": [
    { "Effect": "Allow", "Action": ["s3:GetBucketLocation"], "Resource": "*" },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetBucketLifecycleConfiguration",
        "s3:PutBucketLifecycleConfiguration"
      ],
      "Resource": "arn:aws:s3:::*"
    }
  ]
}
```

---

## 🧼 参考情報

- [Amazon S3 ライフサイクルルールのドキュメント](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
- [AbortIncompleteMultipartUpload の設定例](https://docs.aws.amazon.com/AmazonS3/latest/userguide/mpu-abort-incomplete-mpu-lifecycle-config.html)
- [AWS Trusted Advisor — S3 コスト最適化チェック](https://docs.aws.amazon.com/awssupport/latest/user/trusted-advisor.html)

---

## 🧪 開発メモ

- `put-bucket-lifecycle-configuration` は **全ルールを置換** するため、このツールでは
  既存ルールを読み取り → 必要なルールを追記/更新 → まとめて再適用 という安全な手順をとっています。
- 既に適切なルールがあるバケットは何も変更しません。
- `--export-dir` を活用することで、事前に提案内容をレビューしてから適用できます。

---

👉 **推奨運用**：

1. まず `--suggest --print-rules --print-proposed --export-dir out/ --bucket-file buckets.txt` で全体を確認
2. レビュー後に `--apply` で一括反映
3. 新規バケット対応のため、CI や Lambda 定期実行にも組み込み可能
