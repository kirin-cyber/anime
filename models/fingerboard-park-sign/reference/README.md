# reference

Image to 3D に渡す元画像を置く場所。

```bash
python3 ../src/meshy.py image reference/source-photo.jpg
```

写真自体はリポジトリに含めていない（個人の写真を履歴に残さないため）。
使うときは以下のどちらかで用意する。

- **Mac**: 写真をこのディレクトリに置く
- **リモート実行環境**: チャットに写真を添付すると `/root/.claude/uploads/<session>/<file>` に保存されるので、
  そのパスをそのまま渡す。あるいはこのディレクトリに置いてコミットする
