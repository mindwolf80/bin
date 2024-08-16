# --------------------- Global Variables ---------------------
$scriptDir = $PSScriptRoot
$logDir = Join-Path -Path $scriptDir -ChildPath "logs"
$outputDir = Join-Path -Path $scriptDir -ChildPath "output"
$logFile = Join-Path -Path $logDir -ChildPath "general_log.log"

# Dynamically find the path to plink.exe
$plinkPath = (Get-Command plink.exe -ErrorAction SilentlyContinue).Source

# If plink.exe is not in PATH, set it manually
# $plinkPath = "C:\Path\To\Your\plink.exe"

# Ensure directories exist silently
New-Item -Path $logDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null
New-Item -Path $outputDir -ItemType Directory -Force -ErrorAction SilentlyContinue | Out-Null

# --------------------- Logging Function ---------------------
function Write-Log {
    param (
        [string]$message,
        [string]$level = "INFO"
    )
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $logEntry = "$timestamp - $level - $message"
    Add-Content -Path $logFile -Value $logEntry
    Write-Host $logEntry
}

# --------------------- Utility Functions ---------------------
function Approve-ValidIP {
    param (
        [string]$ip
    )
    return $ip -match '^(?:[0-9]{1,3}\.){3}[0-9]{1,3}$'
}

function Test-Port {
    param (
        [string]$ip,
        [int]$port = 22
    )

    $result = Test-NetConnection -ComputerName $ip -Port $port -InformationLevel Quiet
    return $result
}

function Compare-Inputs {
    param (
        [string]$username,
        [SecureString]$password
    )

    if ([string]::IsNullOrWhiteSpace($username)) {
        throw "Username cannot be empty."
    }

    if ($null -eq $password -or $password.Length -eq 0) {
        throw "Password cannot be empty."
    }
}

function Read-DeviceInfo {
    param (
        [string]$filePath = "devices.csv"  # Generic file path
    )
    $filePath = $filePath.Trim('"')  # Remove surrounding quotes if they exist

    $devices = @{}

    if ($filePath.EndsWith(".csv")) {
        $data = Import-Csv -Path $filePath
    }
    else {
        throw "Invalid file format. Please provide a CSV file."
    }

    foreach ($row in $data) {
        $ip = $row.ip
        $dns = $row.dns
        $command = $row.command -split "`n"

        if ($devices.ContainsKey("$ip|$dns")) {
            $devices["$ip|$dns"] += $command
        }
        else {
            $devices.Add("$ip|$dns", $command)
        }
    }
    return $devices
}

function Start-Command {
    param (
        [string]$ip,
        [string]$dns,
        [string]$username,
        [SecureString]$password,
        [string[]]$commands,
        [string]$plinkPath,
        [SecureString]$enablePassword = $null
    )

    $output = @()
    try {
        $BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($password)
        $plainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
        
        $enableBSTR = $null
        $plainEnablePassword = $null
        if ($enablePassword) {
            $enableBSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($enablePassword)
            $plainEnablePassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($enableBSTR)
        }
        
        # Prepare a script with all commands
        $script = $commands -join '; echo "---COMMAND-SEPARATOR---"; '
        
        # Construct the plink command
        $plinkArgs = @(
            "-ssh",
            "-batch",
            "-pw", $plainPassword,
            "${username}@${ip}"
        )

        # Start plink process
        $plink = Start-Process -FilePath $plinkPath -ArgumentList $plinkArgs -NoNewWindow -PassThru -RedirectStandardOutput "stdout.txt" -RedirectStandardError "stderr.txt" -RedirectStandardInput

        # Monitor the process and handle prompts
        $enableSent = $false
        while (!$plink.HasExited) {
            $stderr = Get-Content "stderr.txt" -Tail 1 -ErrorAction SilentlyContinue
            $stdout = Get-Content "stdout.txt" -Tail 1 -ErrorAction SilentlyContinue

            if ($stderr -match "Are you sure you want to continue connecting \(yes/no/\[fingerprint\]\)\?") {
                $plink.StandardInput.WriteLine("yes")
                Start-Sleep -Milliseconds 500
            }
            elseif ($stderr -match "Press Enter to continue" -or $stderr -match "Press Return to continue") {
                $plink.StandardInput.WriteLine("")
                Start-Sleep -Milliseconds 500
            }
            elseif ($stdout -match ">$" -and !$enableSent -and $plainEnablePassword) {
                $plink.StandardInput.WriteLine("enable")
                Start-Sleep -Milliseconds 500
                $plink.StandardInput.WriteLine($plainEnablePassword)
                $enableSent = $true
                Start-Sleep -Milliseconds 1000
            }
            elseif ($stdout -match "#$") {
                $plink.StandardInput.WriteLine($script)
                break
            }
            
            Start-Sleep -Milliseconds 100
        }

        $plink.WaitForExit()

        # Read the output
        $commandResult = Get-Content "stdout.txt" -Raw
        Remove-Item "stdout.txt", "stderr.txt" -ErrorAction SilentlyContinue

        # Split the result into individual command outputs
        $commandResults = $commandResult -split "---COMMAND-SEPARATOR---"

        for ($i = 0; $i -lt $commands.Length; $i++) {
            $commandOutput = if ($i -lt $commandResults.Length) { $commandResults[$i].Trim() } else { "No output" }
            $output += [PSCustomObject]@{
                Command = $commands[$i]
                Result = $commandOutput
            }
            # Display output in terminal
            Write-Host "Command: $($commands[$i])"
            Write-Host "Result: $commandOutput"
            Write-Host "------------------------"
        }
    }
    catch {
        $errorType = $_.Exception.GetType().FullName
        $errorMessage = "FAILURE: Commands on device ${ip} failed. Error type: ${errorType}. Details: $_"
        Write-Log $errorMessage "ERROR"
        Write-Host $errorMessage -ForegroundColor Red -BackgroundColor Black
        $output += [PSCustomObject]@{
            Command = "Multiple commands"
            Result = "FAILURE: $errorMessage"
        }
    }
    finally {
        if ($BSTR) {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)
        }
        if ($enableBSTR) {
            [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($enableBSTR)
        }
    }
    return $output
}

function Format-Output {
    param (
        [hashtable]$devices
    )
    
    $formattedOutput = @()
    $currentIP = $null
    $currentDNS = $null

    foreach ($deviceKey in $devices.Keys) {
        $ip, $dns = $deviceKey -split '\|'
        $commandsOutput = $devices[$deviceKey]

        foreach ($commandOutput in $commandsOutput) {
            if ($ip -ne $currentIP -or $dns -ne $currentDNS) {
                $formattedOutput += [pscustomobject]@{
                    IP = $ip
                    DNS = $dns
                    Command = $commandOutput.Command
                    Result = $commandOutput.Result
                }
                $currentIP = $ip
                $currentDNS = $dns
            } else {
                $formattedOutput += [pscustomobject]@{
                    IP = ""
                    DNS = ""
                    Command = $commandOutput.Command
                    Result = $commandOutput.Result
                }
            }
        }
    }
    return $formattedOutput
}

function Push-Workflow {
    param (
        [string]$username = "root",
        [SecureString]$password = (ConvertTo-SecureString "fuzzy.Mass24" -AsPlainText -Force),
        [SecureString]$enablePassword = $null,
        [hashtable]$devices,
        [int]$timeout = 0,
        [string]$logFilePath,
        [string]$plinkPath,
        [string]$inputSource = "Manual"
    )

    # Validate inputs
    try {
        Compare-Inputs -username $username -password $password
    }
    catch {
        Write-Log $_ "ERROR"
        throw $_
    }

    $deviceKeys = @($devices.Keys)
    $allResults = @{}
    $totalDevices = $devices.Count
    $currentDevice = 0
    $failedCommands = @()

    foreach ($deviceKey in $deviceKeys) {
        $currentDevice++
        $ip, $dns = $deviceKey -split '\|'
        $commands = $devices[$deviceKey]
        
        Write-Host "Processing device ${currentDevice} of ${totalDevices}: ${ip}" -ForegroundColor Cyan
        
        if (Test-Port -ip $ip -port 22) {
            Write-Log "SSH port 22 is open on $ip. Attempting to connect..." "INFO"
            $results = Start-Command -ip $ip -dns $dns -username $username -password $password -commands $commands -plinkPath $plinkPath -enablePassword $enablePassword
            $failedCommands += $results | Where-Object { $_.Result.StartsWith("FAILURE:") }
            $allResults[$deviceKey] = $results
        }
        else {
            $errorMessage = "SSH port 22 is not open on $ip. Skipping device."
            Write-Log $errorMessage "ERROR"
            Write-Host $errorMessage -ForegroundColor Red
        }

        if ($timeout -gt 0) {
            Start-Sleep -Seconds $timeout
        }
    }

    $formattedOutput = Format-Output -devices $allResults

    # Create a timestamp
    $timestamp = Get-Date -Format "yyyyMMdd_HHmmss"

    # Create the filename with timestamp and input source
    $fileName = "output_{0}_{1}.csv" -f $inputSource, $timestamp
    $outputCsvPath = Join-Path -Path $outputDir -ChildPath $fileName

    # Save the output
    $formattedOutput | Export-Csv -Path $outputCsvPath -NoTypeInformation -Encoding UTF8

    Write-Log "Commands executed and output saved to $outputCsvPath" "INFO"

    if ($failedCommands.Count -gt 0) {
        Write-Host "`nFAILURE SUMMARY:" -ForegroundColor Red -BackgroundColor Black
        foreach ($failure in $failedCommands) {
            Write-Host "Device: $($failure.IP), Command: $($failure.Command)" -ForegroundColor Red
        }
    } else {
        Write-Host "`nAll commands completed successfully." -ForegroundColor Green
    }

    Write-Host "All devices processed." -ForegroundColor Green
}

# --------------------- Script Execution ---------------------
function Initialize-Script {
    # Check if the plink.exe file was found
    if (-not $plinkPath) {
        Write-Log "Error: plink.exe not found in the system path." "ERROR"
        return
    }

    $devices = @{}
    $inputSource = ""

    # Ask user for input method
    $inputMethod = Read-Host "Enter '1' to use predefined devices or '2' to read from a CSV file"

    if ($inputMethod -eq '1') {
        # Example of predefined devices and commands
        $devices.Add("192.168.1.1", @("show version", "show interface"))
        # $devices.Add("192.168.1.2", @("ping -c 4 8.8.8.8", "traceroute 8.8.8.8", "nslookup google.com"))
        
        # Uncomment the following section for Cisco ASA devices
        <#
        $devices.Add("192.168.1.100", @(
            "enable",
            "show version",
            "show interface",
            "show run"
        ))
        #>
        
        $inputSource = "Predefined"
    }
    elseif ($inputMethod -eq '2') {
        $csvPath = Read-Host "Enter the path to your CSV file"
        $devices = Read-DeviceInfo -filePath $csvPath
        $inputSource = [System.IO.Path]::GetFileNameWithoutExtension($csvPath)
    }
    else {
        Write-Log "Invalid input. Exiting script." "ERROR"
        return
    }

    $timeout = 5  # Example timeout value in seconds
    
    # Uncomment the following line for Cisco ASA devices
    # $enablePassword = Read-Host "Enter the enable password for Cisco devices (leave blank if not needed)" -AsSecureString
    
    # If not using Cisco ASA devices, use $null for enablePassword
    $enablePassword = $null

    Push-Workflow -devices $devices -timeout $timeout -logFilePath $logFile -plinkPath $plinkPath -inputSource $inputSource -enablePassword $enablePassword
}

# Give the user an option to run the script again
do {
    Initialize-Script
    $again = Read-Host "Do you want to run the script again? (Y/N)"
} while ($again -eq "Y" -or $again -eq "y")

Write-Host "Script execution completed. Press Enter to exit."
Read-Host