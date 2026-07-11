# 動作確認用フロント画面（inuki）配信用コンテナイメージ。
#
# frontend/index.html（単一の静的HTMLファイル）をnginxで配信するだけの
# 最小構成。ビルドツールやフレームワークは使用していない。
#
# ビルドコンテキストはリポジトリルート（`docker build -f docker/frontend/Dockerfile .`）を
# 想定する。
#
# Cloud Runは環境変数PORTでリスンポートを指定するため、公式nginxイメージの
# テンプレート機能（/etc/nginx/templates配下の*.templateをコンテナ起動時に
# envsubstで展開し/etc/nginx/conf.d/に配置する仕組み）を利用してポートを
# 動的に反映する。

FROM nginx:1.27-alpine

COPY frontend/index.html /usr/share/nginx/html/index.html
COPY frontend/demo.html /usr/share/nginx/html/demo.html
COPY frontend/terms.html /usr/share/nginx/html/terms.html
COPY frontend/privacy.html /usr/share/nginx/html/privacy.html
COPY frontend/faq.html /usr/share/nginx/html/faq.html
COPY frontend/contact.html /usr/share/nginx/html/contact.html
COPY frontend/img/ /usr/share/nginx/html/img/
COPY docker/frontend/default.conf.template /etc/nginx/templates/default.conf.template

ENV PORT=8080
EXPOSE 8080
