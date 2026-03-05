#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# QA Intelligence Agent – One-command setup for Mac / Linux
# Usage: bash setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m'

echo ""
echo -e "${BLUE}══════════════════════════════════════════════${NC}"
echo -e "${BLUE}   QA Intelligence Agent – Setup             ${NC}"
echo -e "${BLUE}══════════════════════════════════════════════${NC}"
echo ""

# ── Python check ──────────────────────────────────────────────────────────────
echo -e "${YELLOW}[1/5] Checking Python version...${NC}"
if ! command -v python3 &>/dev/null; then
    echo -e "${RED}ERROR: Python 3 not found.${NC}"
    echo "Please install Python 3.10+ from https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
REQUIRED="3.10"
if python3 -c "import sys; exit(0 if sys.version_info >= (3,10) else 1)"; then
    echo -e "${GREEN}✓ Python $PYTHON_VERSION found${NC}"
else
    echo -e "${RED}ERROR: Python $PYTHON_VERSION found, but 3.10+ is required.${NC}"
    exit 1
fi

# ── Virtual environment ────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[2/5] Creating virtual environment...${NC}"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo -e "${GREEN}✓ Virtual environment created at .venv/${NC}"
else
    echo -e "${GREEN}✓ Virtual environment already exists${NC}"
fi

# Activate
source .venv/bin/activate

# ── Install dependencies ───────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[3/5] Installing dependencies (this may take 1-2 minutes)...${NC}"
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
echo -e "${GREEN}✓ All dependencies installed${NC}"

# ── .env setup ────────────────────────────────────────────────────────────────
echo ""
echo -e "${YELLOW}[4/5] Setting up configuration...${NC}"

if [ ! -f ".env" ]; then
    cp .env.example .env
    echo ""
    echo -e "${YELLOW}  ┌─────────────────────────────────────────────────────┐${NC}"
    echo -e "${YELLOW}  │  ACTION REQUIRED: Enter your OpenAI API key below  │${NC}"
    echo -e "${YELLOW}  └─────────────────────────────────────────────────────┘${NC}"
    echo ""
    read -rp "  Paste your OpenAI API key (sk-...): " API_KEY

    if [[ -z "$API_KEY" ]]; then
        echo -e "${RED}  No key entered. Edit .env manually before running.${NC}"
    else
        # Write full .env
        cat > .env <<EOF
OPENAI_API_KEY=${API_KEY}
OPENAI_MODEL=gpt-4o
OPENAI_MAX_TOKENS=2000
DATABASE_URL=sqlite:///./data/qa_agent.db
SCHEDULE_INTERVAL_HOURS=6
MIN_RELEVANCE_SCORE=40
REPORTS_DIR=./reports
LOG_LEVEL=INFO
LOG_DIR=./logs
EOF
        echo -e "${GREEN}  ✓ .env configured${NC}"
    fi
else
    echo -e "${GREEN}  ✓ .env already exists (not overwritten)${NC}"
fi

# ── Create directories ─────────────────────────────────────────────────────────
mkdir -p data reports logs
echo -e "${GREEN}✓ Directories ready (data/, reports/, logs/)${NC}"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo -e "${BLUE}══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✓ Setup complete!${NC}"
echo -e "${BLUE}══════════════════════════════════════════════${NC}"
echo ""
echo -e "${YELLOW}[5/5] How to run:${NC}"
echo ""
echo "  # Activate the environment (run this every time you open a terminal):"
echo "  source .venv/bin/activate"
echo ""
echo "  # Run once (generates a report and exits):"
echo "  python3 main.py run"
echo ""
echo "  # Run automatically every 6 hours (daemon mode):"
echo "  python3 main.py schedule"
echo ""
echo "  # View run history:"
echo "  python3 main.py status"
echo ""
echo "  # Reports are saved to: $(pwd)/reports/"
echo ""
