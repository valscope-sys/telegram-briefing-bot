#!/bin/bash
cd /home/ubuntu/telegram-briefing-bot

# 1. 뇌(market_context + briefing history) 변경사항 먼저 커밋+푸시
git add telegram_bot/history/ 2>/dev/null
git diff --cached --quiet || {
    git config user.name "noderesearch-bot"
    git config user.email "bot@noderesearch.com"
    git commit -m "auto: save brain [$(date +%Y-%m-%d\ %H:%M)]"
    git push
}

# 2. 최신 코드 가져오기
git pull origin main

# 3. 패키지 업데이트 + 서비스 재시작
source venv/bin/activate
pip install -r telegram_bot/requirements.txt -q
sudo systemctl restart telegram-bot
