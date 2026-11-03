$ErrorActionPreference = "Stop"

$secureSecret = Read-Host "Introduce el REMINDER_TRIGGER_SECRET configurado en Render" -AsSecureString
$secretPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureSecret)

try {
    $env:REMINDER_TRIGGER_SECRET = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($secretPointer)
    if ([string]::IsNullOrWhiteSpace($env:REMINDER_TRIGGER_SECRET)) {
        throw "REMINDER_TRIGGER_SECRET cannot be empty."
    }

    $endpoint = "https://miproyecto-e1o4.onrender.com/api/internal/process-reminders"

    & npx neon@latest functions deploy auctionreminders `
        --src functions/auctionreminders/index.mjs `
        --env "REMINDER_ENDPOINT_URL=$endpoint" `
        --env "REMINDER_TRIGGER_SECRET=$env:REMINDER_TRIGGER_SECRET" `
        --wait
    if ($LASTEXITCODE -ne 0) {
        throw "Neon function deployment failed with exit code $LASTEXITCODE."
    }

    & npx neon@latest triggers create `
        --function-slug auctionreminders `
        --name auction-reminders `
        --cron "*/5 * * * *"
    if ($LASTEXITCODE -ne 0) {
        throw "Neon trigger creation failed with exit code $LASTEXITCODE."
    }
}
finally {
    Remove-Item Env:REMINDER_TRIGGER_SECRET -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($secretPointer)
}
