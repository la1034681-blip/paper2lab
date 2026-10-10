# 1) 旧样本移入回收站(可恢复); 2) 下载新的五套真实论文+官方代码
$root = "C:\Users\lijiahui\Desktop\Paper2Lab测试集"
Add-Type -AssemblyName Microsoft.VisualBasic
$log = @()

foreach ($d in @("01_BERT", "02_pix2pix", "03_TabNet", "04_SimSiam", "05_SimCLR")) {
    $p = Join-Path $root $d
    if (Test-Path $p) {
        [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory(
            $p, 'OnlyErrorDialogs', 'SendToRecycleBin')
        $log += "trash: $d"
    }
}

# 新样本: (目录, arXiv PDF, GitHub 仓库)
$samples = @(
    @{ dir = "01_MoCo";     pdf = "https://arxiv.org/pdf/1911.05722"; repo = "facebookresearch/moco" },
    @{ dir = "02_DETR";     pdf = "https://arxiv.org/pdf/2005.12872"; repo = "facebookresearch/detr" },
    @{ dir = "03_NeRF";     pdf = "https://arxiv.org/pdf/2003.08934"; repo = "bmild/nerf" },
    @{ dir = "04_PointNet"; pdf = "https://arxiv.org/pdf/1612.00593"; repo = "charlesq34/pointnet" },
    @{ dir = "05_ViT";      pdf = "https://arxiv.org/pdf/2010.11929"; repo = "google-research/vision_transformer" }
)

foreach ($s in $samples) {
    $d = Join-Path $root $s.dir
    New-Item -ItemType Directory -Force -Path $d | Out-Null
    $pdf = Join-Path $d "paper.pdf"
    $zip = Join-Path $d "code.zip"
    curl.exe -sL --max-time 120 -o $pdf $s.pdf
    $psize = (Get-Item $pdf).Length
    $head = [System.Text.Encoding]::ASCII.GetString([System.IO.File]::ReadAllBytes($pdf)[0..3])
    $log += "$($s.dir) PDF $([math]::Round($psize/1KB,0))KB head=$head"

    $got = $false
    foreach ($br in @("master", "main", "develop")) {
        if ($got) { break }
        $url = "https://codeload.github.com/$($s.repo)/zip/refs/heads/$br"
        curl.exe -sL --max-time 180 -o $zip $url
        if ((Test-Path $zip) -and (Get-Item $zip).Length -gt 20000) {
            $zsize = (Get-Item $zip).Length
            $log += "  ZIP($br) $([math]::Round($zsize/1MB,2))MB"
            $got = $true
        }
    }
    if (-not $got) { $log += "  ZIP FAILED for $($s.repo)" }
}

$log | Set-Content -Path (Join-Path $root "download.log.txt") -Encoding utf8
$log
