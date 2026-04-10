#!/bin/bash
cd /home/ubuntu/telegram-briefing-bot

# 1. 뇌(market_context + briefing history) 변경사항 커밋+푸시
git add telegram_bot/history/ 2>/dev/null
git diff --cached --quiet || {
    git config user.name "noderesearch-bot"
    git config user.email "bot@noderesearch.com"
    git commit -m "auto: save brain [$(date +%Y-%m-%d\ %H:%M)]"
    git push
}

# 2. 최신 코드 가져오기
BEFORE=$(git rev-parse HEAD)
git pull origin main
AFTER=$(git rev-parse HEAD)

# 3. 외부에서 코드 변경이 있었을 때만 재시작
if [ "$BEFORE" != "$AFTER" ]; then
    source venv/bin/activate
    pip install -r telegram_bot/requirements.txt -q
    sudo systemctl restart telegram-bot
    echo "[DEPLOY] $(date) - 외부 코드 변경 감지, 재시작 완료"
else
    echo "[DEPLOY] $(date) - 변경 없음, 스킵"
fi
