@echo off
REM Script de démarrage du Système d'Arrosage Intelligent
REM
REM Prérequis:
REM  - Python 3.8+
REM  - MongoDB Server en cours d'exécution (ou à installer)
REM  - pip installé

echo.
echo ============================================
echo Système d'Arrosage Intelligent
echo ============================================
echo.

REM Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [!] Python n'est pas installé ou non disponible dans PATH
    echo Téléchargez Python depuis https://www.python.org
    pause
    exit /b 1
)

echo [✓] Python trouvé

REM Check MongoDB
mongod --version >nul 2>&1
if errorlevel 1 (
    echo [!] MongoDB n'est pas disponible. Le système tournera SANS persistance.
    echo Pour installer MongoDB: https://www.mongodb.com/try/download/community
    pause
) else (
    echo [✓] MongoDB trouvé
)

REM Install dependencies
echo.
echo Vérification des dépendances...
pip install -q -r backend\requirements.txt

if errorlevel 1 (
    echo [!] Erreur lors de l'installation des dépendances
    pause
    exit /b 1
)

echo [✓] Dépendances installées

REM Start backend
echo.
echo Démarrage du backend...
cd backend
python app.py

pause
