@echo off
:menu
cls
echo ============================================
echo               Git Command Menu
echo ============================================
echo Current Repository: %cd%
echo ============================================
echo 1. Setup (Init ^& Configure)
echo.
echo 2. Basic Workflow (Add, Commit, Push)
echo.
echo 3. Sync with Remote (Pull ^& Rebase)
echo.
echo 4. Manage Remotes (Check or Update URL)
echo.
echo 5. Forceful Actions (Push or Overwrite)
echo.
echo 6. Fetch Updates ^& Check Status
echo.
echo 7. Undo Last Commit
echo.
echo 8. Backup Repository
echo.
echo 9. Help
echo.
echo 10. Exit
echo ============================================
set /p choice=Enter your choice (1-10): 

if "%choice%"=="1" goto setup
if "%choice%"=="2" goto workflow
if "%choice%"=="3" goto sync
if "%choice%"=="4" goto remotes
if "%choice%"=="5" goto forceful
if "%choice%"=="6" goto fetch_status
if "%choice%"=="7" goto undo_commit
if "%choice%"=="8" goto backup
if "%choice%"=="9" goto help
if "%choice%"=="10" goto exit
echo Invalid choice, please try again.
pause
goto menu

:setup
cls
echo === Setup Commands ===
echo Description: Configure repository settings and initialize Git.
echo 1. Initialize Git Repository
echo.
echo 2. Configure User Name
echo.
echo 3. Configure User Email
echo.
echo 4. Back to Main Menu
set /p choice=Enter your choice (1-4): 
if "%choice%"=="1" (
    git init
    echo Repository initialized.
    pause
    goto setup
)
if "%choice%"=="2" (
    set /p username=Enter your Git user name: 
    git config user.name "%username%"
    echo User name configured.
    pause
    goto setup
)
if "%choice%"=="3" (
    set /p email=Enter your Git email: 
    git config user.email "%email%"
    echo Email configured.
    pause
    goto setup
)
if "%choice%"=="4" goto menu
echo Invalid choice, please try again.
pause
goto setup

:workflow
cls
echo === Basic Workflow Commands ===
echo Description: Perform day-to-day Git tasks like adding, committing, and pushing changes.
echo 1. Add All Files
echo.
echo 2. Commit Changes
echo.
echo 3. Push Changes
echo.
echo 4. Remove Files from Git
echo.
echo 5. Back to Main Menu
echo.
set /p choice=Enter your choice (1-5): 
if "%choice%"=="1" (
    git add .
    echo Files added.
    pause
    goto workflow
)
if "%choice%"=="2" (
    set /p message=Enter commit message: 
    git commit -m "%message%"
    echo Changes committed.
    pause
    goto workflow
)
if "%choice%"=="3" (
    git push -u origin main
    echo Changes pushed.
    pause
    goto workflow
)
if "%choice%"=="4" (
    set /p file=Enter the file or directory to remove from Git: 
    git rm --cached "%file%"
    echo File removed from Git tracking. Remember to commit the changes.
    pause
    goto workflow
)
if "%choice%"=="5" goto menu
echo Invalid choice, please try again.
pause
goto workflow

:sync
cls
echo === Sync with Remote Commands ===
echo Description: Pull updates from the remote repository.
echo 1. Pull Changes (Rebase)
echo.
echo 2. Back to Main Menu
echo.
set /p choice=Enter your choice (1-2): 
if "%choice%"=="1" (
    git pull --rebase
    echo Pull with rebase complete.
    pause
    goto sync
)
if "%choice%"=="2" goto menu
echo Invalid choice, please try again.
pause
goto sync

:remotes
cls
echo === Remote Management Commands ===
echo Description: Manage your repository's remote URL.
echo 1. Check Remote URL
echo.
echo 2. Update Remote URL
echo.
echo 3. Back to Main Menu
set /p choice=Enter your choice (1-3): 
if "%choice%"=="1" (
    git remote -v
    pause
    goto remotes
)
if "%choice%"=="2" (
    set /p new_url=Enter new remote URL: 
    git remote set-url origin %new_url%
    echo Remote URL updated.
    pause
    goto remotes
)
if "%choice%"=="3" goto menu
echo Invalid choice, please try again.
pause
goto remotes

:forceful
cls
echo === Forceful Actions ===
echo Description: Use advanced commands like force-push.
echo 1. Force Push Changes
echo.
echo 2. Back to Main Menu
echo.
set /p choice=Enter your choice (1-2): 
if "%choice%"=="1" (
    git push --force
    echo Force push complete.
    pause
    goto forceful
)
if "%choice%"=="2" goto menu
echo Invalid choice, please try again.
pause
goto forceful

:fetch_status
cls
echo Fetching updates and checking repository status...
git fetch
git status
pause
goto menu

:undo_commit
cls
echo Undoing last commit...
git reset --soft HEAD~1
echo Last commit undone. Changes are now staged.
pause
goto menu

:backup
cls
echo Backing up repository...
set /p backup_path=Enter backup destination path: 
xcopy /E /I . "%backup_path%"
echo Backup complete.
pause
goto menu

:help
cls
echo === Help Menu ===
echo Use the numbered options to execute specific Git commands.
echo Each option corresponds to a common task in Git.
pause
goto menu

:exit
exit /b %ERRORLEVEL%
