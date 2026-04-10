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

# 2. 최신 코드 가져오기 — 변경 있을 때만 재시작
BEFORE=$(git rev-parse HEAD)
git pull origin main
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" != "$AFTER" ]; then
    # 코드 변경됨 → 패키지 업데이트 + 서비스 재시작
    source venv/bin/activate
    pip install -r telegram_bot/requirements.txt -q
    sudo systemctl restart telegram-bot
    echo "[DEPLOY] $(date) - 코드 변경 감지, 서비스 재시작"
else
    echo "[DEPLOY] $(date) - 변경 없음, 스킵"
fi
