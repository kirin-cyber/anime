# FINGERBOARD PARK サイン — 3D モデル

指スケ（フィンガーボード）用の合板レーザーカット製ミニ看板を 3D モデル化したもの。
写真の実物を採寸のうえ再現し、パラメトリックなビルドスクリプトから
STL / GLB とレーザーカット用 SVG を生成する。

![プレビュー](out/preview-hero.png)

| | |
|---|---|
| ![正面](out/preview-front.png) | ![斜め](out/preview-side.png) |

## 出力物

| ファイル | 用途 |
|---|---|
| [`out/fingerboard-park-sign.stl`](out/fingerboard-park-sign.stl) | 3D プリント（watertight・単一ソリッド） |
| [`out/fingerboard-park-sign.glb`](out/fingerboard-park-sign.glb) | ビューワ／Blender／Web 表示 |
| [`out/fingerboard-park-sign-lasercut.svg`](out/fingerboard-park-sign-lasercut.svg) | レーザー加工用（原寸 1:1） |
| `out/preview-*.png` | レンダリング画像 |

## 寸法

全体 **W 80.0 × D 20.0 × H 48.6 mm**（体積 7.78 cm³）。
指スケのデッキ（約 96 mm）と並べたときのスケール感に合わせてある。

| 部位 | 寸法 |
|---|---|
| 看板プレート | 80 × 22.6 mm / 板厚 3 mm |
| 文字（大文字高） | 8.7 mm、2 行（FINGERBOARD / PARK） |
| レリーフ（文字・フチの立ち上がり） | 1.2 mm |
| 彫り線（二重線） | 幅 0.6 mm / 深さ 0.5 mm |
| 支柱 | 幅 7.5 mm × 厚 3 mm、台座上面から 20 mm |
| 台座 | 20 mm 角 + 19 mm 角の合板 2 枚重ね（各 3 mm） |

## 構成の考え方

写真の実物は「板を彫り下げて文字とフチだけを残す」典型的なレーザー加工サイン。
モデルもその手順どおりに組み立てている。

1. 書体の輪郭をベクタとして取り出し、2 行に組む
2. 文字シルエットを 2.6 mm オフセットして角を丸め、プレート外形にする
3. プレートを厚 3 mm で押し出し、文字と外周フチ（幅 1.8 mm）を 1.2 mm 立ち上げる
4. 文字とフチの内側 0.55 mm に、幅 0.6 mm・深さ 0.5 mm の彫り線を掘る（写真の二重線）
5. 支柱と 2 枚重ねの台座を結合し、単一の watertight ソリッドにする

書体は実物に合わせ、角ばったグロテスク体 [Tektur](https://github.com/hyvyys/Tektur)
（SIL OFL, `src/fonts/OFL.txt`）を 0.72 mm 太らせて使用している。

## ビルド

```bash
pip install -r requirements.txt
python3 src/build.py      # STL / GLB を out/ に出力
python3 src/lasercut.py   # レーザーカット用 SVG を出力
python3 src/render.py     # プレビュー画像を出力
```

寸法・文字・書体はすべて `src/build.py` 冒頭の定数で変更できる。
たとえば文言を変えるなら `LINE1` / `LINE2`、大きさを変えるなら `TARGET_WIDTH` を触る。

| ファイル | 役割 |
|---|---|
| `src/build.py` | 寸法定義・2D 形状生成・3D ブーリアン・エクスポート |
| `src/glyphs.py` | TrueType の輪郭を shapely ポリゴンに変換 |
| `src/lasercut.py` | 切断／彫刻レイヤ分けした SVG を出力 |
| `src/render.py` | numpy + PIL の自前ラスタライザによるプレビュー生成 |

## レーザーカットで作る場合

SVG は 1 単位 = 1 mm の原寸。レイヤは色で分けてある。

- **赤 `#ff0000`** — 切断（本体シルエット、台座 2 枚とスリット）
- **青 `#0000ff`** — 彫刻ライン（文字の輪郭、その内側の二重線、外周の内側線）
- **グレー塗り** — 面彫刻（掘り下げる地の部分）

材料は 3 mm 合板。本体 1 枚と台座 2 枚を切り出し、支柱を台座のスリットに通して接着する。
スリットは板厚 3.0 mm ちょうどで引いてあるので、レーザーのカーフ分は加工機に合わせて調整のこと。

## Meshy で生成したい場合

この実行環境からは `api.meshy.ai` への接続がネットワークポリシーで遮断されており
（`CONNECT` が 403）、API キーも設定されていないため、Meshy 側での生成は実行できていない。
Meshy を使うなら、元写真をそのまま Image to 3D に入れるのが最短。
Text to 3D で作る場合のプロンプト例:

> A small laser-cut plywood sign for a fingerboard skatepark. Two lines of bold squared
> sans-serif text reading "FINGERBOARD" over "PARK", raised in relief on a rounded plaque
> whose outline follows the letters. A thin engraved outline runs inside each letter and
> inside the plaque border; the recessed background is darkened by laser burn. The plaque
> sits on a narrow vertical post mounted in a small square two-layer plywood base.
> Natural birch plywood, matte finish, product photo on a white background.

なお本モデルは寸法が確定した CAD 的なソリッドで、Meshy の生成結果とは性質が異なる
（Meshy はスキャン風のメッシュとテクスチャを返す）。原寸で作りたい場合はこちらを、
質感重視のビジュアルが欲しい場合は Meshy を、という使い分けになる。
