# KRX 정보데이터시스템 접근성 테스트 (작업 스케줄러 = 실제 네트워크 컨텍스트)
$out = "C:\stock\logs\krx-net-test.txt"
try {
    $r = Invoke-WebRequest -Uri "https://data.krx.go.kr/comm/bldAttendant/getJsonData.cmd" -Method POST `
        -Body @{ bld = "dbms/MDC/STAT/standard/MDCSTAT00301"; locale = "ko_KR" } `
        -Headers @{ "User-Agent" = "Mozilla/5.0"; "Referer" = "https://data.krx.go.kr/contents/MDC/MDI/mdiLoader/index.cmd" } `
        -TimeoutSec 15 -UseBasicParsing
    "STATUS=$($r.StatusCode)`nBODY=$($r.Content.Substring(0, [Math]::Min(300, $r.Content.Length)))" | Out-File $out -Encoding utf8
} catch {
    "ERROR=$($_.Exception.Message)" | Out-File $out -Encoding utf8
}
