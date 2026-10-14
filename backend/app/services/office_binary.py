"""用本机 Word / Excel 套打旧的 .doc、.xls 模板。"""
import json
import subprocess
import tempfile
from pathlib import Path

from ..errors import BizError

_SCRIPT = r"""
$ErrorActionPreference = "Stop"
$payload = Get-Content -LiteralPath $args[0] -Raw -Encoding UTF8 | ConvertFrom-Json
$src = [string]$payload.src
$out = [string]$payload.out
$kind = [string]$payload.kind
function Apply-Map([string]$text, $map) {
  if (-not $text -or $text -notlike "*{{*") { return $text }
  foreach ($prop in $map.PSObject.Properties) {
    $token = "{{" + $prop.Name + "}}"
    if ($text.Contains($token)) { $text = $text.Replace($token, [string]$prop.Value) }
  }
  return $text
}
if ($kind -eq "xls") {
  $excel = New-Object -ComObject Excel.Application
  $excel.Visible = $false
  $excel.DisplayAlerts = $false
  $book = $excel.Workbooks.Open($src)
  try {
    foreach ($sheet in $book.Worksheets) {
      $maxRow = [Math]::Max(1, $sheet.UsedRange.Row + $sheet.UsedRange.Rows.Count - 1)
      $maxCol = [Math]::Max(1, $sheet.UsedRange.Column + $sheet.UsedRange.Columns.Count - 1)
      $groups = @($payload.groups)
      for ($g = $groups.Count - 1; $g -ge 0; $g--) {
        $group = $groups[$g]
        $keys = @($group.keys)
        $best = 0
        $bestRow = 0
        for ($r = 1; $r -le $maxRow; $r++) {
          $blob = ""
          for ($c = 1; $c -le $maxCol; $c++) { $blob += [string]$sheet.Cells.Item($r, $c).Text }
          $hits = 0
          foreach ($key in $keys) { if ($blob.Contains("{{" + $key + "}}")) { $hits++ } }
          if ($hits -gt $best) { $best = $hits; $bestRow = $r }
        }
        if ($bestRow -eq 0) { continue }
        $items = @($group.rows)
        if ($items.Count -eq 0) { $items = @(@{}) }
        if ($items.Count -gt 1) {
          $sheet.Rows.Item($bestRow).Copy()
          $sheet.Rows.Item(($bestRow + 1)).Resize($items.Count - 1).Insert() | Out-Null
        }
        for ($offset = 0; $offset -lt $items.Count; $offset++) {
          for ($c = 1; $c -le $maxCol; $c++) {
            $cell = $sheet.Cells.Item($bestRow + $offset, $c)
            $cell.Value2 = Apply-Map ([string]$cell.Text) $items[$offset]
          }
        }
        $maxRow = $maxRow + ($items.Count - 1)
      }
      for ($r = 1; $r -le $maxRow; $r++) {
        for ($c = 1; $c -le $maxCol; $c++) {
          $cell = $sheet.Cells.Item($r, $c)
          $text = [string]$cell.Text
          if ($text -like "*{{*") { $cell.Value2 = Apply-Map $text $payload.mapping }
        }
      }
    }
    if ([IO.Path]::GetExtension($out).ToLower() -eq ".xls") { $book.SaveAs($out, 56) } else { $book.SaveAs($out, 51) }
  } finally {
    $book.Close($false)
    $excel.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($book) | Out-Null
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($excel) | Out-Null
  }
} else {
  $word = New-Object -ComObject Word.Application
  $word.Visible = $false
  $word.DisplayAlerts = 0
  $doc = $word.Documents.Open($src)
  try {
    foreach ($table in @($doc.Tables)) {
      foreach ($group in @($payload.groups)) {
        $keys = @($group.keys)
        $best = 0
        $bestRow = $null
        foreach ($row in @($table.Rows)) {
          $blob = [string]$row.Range.Text
          $hits = 0
          foreach ($key in $keys) { if ($blob.Contains("{{" + $key + "}}")) { $hits++ } }
          if ($hits -gt $best) { $best = $hits; $bestRow = $row }
        }
        if ($null -eq $bestRow) { continue }
        $items = @($group.rows)
        if ($items.Count -eq 0) { $items = @(@{}) }
        $start = $bestRow.Index
        for ($extra = 1; $extra -lt $items.Count; $extra++) { $table.Rows.Add($bestRow) | Out-Null }
        for ($offset = 0; $offset -lt $items.Count; $offset++) {
          $row = $table.Rows.Item($start + $offset)
          foreach ($cell in @($row.Cells)) {
            $text = [string]$cell.Range.Text
            $text = $text.TrimEnd([char]13, [char]7)
            $cell.Range.Text = Apply-Map $text $items[$offset]
          }
        }
      }
    }
    $find = $doc.Content.Find
    $find.ClearFormatting()
    $find.Replacement.ClearFormatting()
    foreach ($prop in $payload.mapping.PSObject.Properties) {
      $find.Execute("{{" + $prop.Name + "}}", $false, $false, $false, $false, $false, $true, 1, $false, [string]$prop.Value, 2) | Out-Null
    }
    $format = 0
    if ([IO.Path]::GetExtension($out).ToLower() -eq ".docx") { $format = 12 }
    $doc.SaveAs([ref]$out, [ref]$format)
  } finally {
    $doc.Close($false)
    $word.Quit()
  }
}
"""


def render_binary(path: Path, mapping: dict, groups, kind: str) -> bytes:
    app = "Excel" if kind == "xls" else "Word"
    payload = {
        "src": str(path),
        "kind": kind,
        "mapping": {str(key): "" if value is None else str(value) for key, value in (mapping or {}).items()},
        "groups": [
            {
                "keys": [str(key) for key in keys],
                "rows": [{str(key): "" if value is None else str(value) for key, value in row.items()} for row in rows],
            }
            for keys, rows in groups
        ],
    }
    try:
        with tempfile.TemporaryDirectory() as folder:
            folder_path = Path(folder)
            spec = folder_path / "fill.json"
            script = folder_path / "fill.ps1"
            target = folder_path / f"out{path.suffix.lower()}"
            payload["out"] = str(target)
            spec.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            script.write_text(_SCRIPT, encoding="utf-8-sig")
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-File", str(script), str(spec)],
                capture_output=True,
                text=True,
                timeout=90,
                check=False,
            )
            if completed.returncode != 0 or not target.is_file():
                detail = (completed.stderr or completed.stdout or "").strip().splitlines()
                tail = detail[-1] if detail else ""
                raise BizError(f"这个模板是 {path.suffix}，需要本机安装 {app} 才能生成。{tail}".strip())
            return target.read_bytes()
    except subprocess.TimeoutExpired as exc:
        raise BizError(f"调用 {app} 生成超时") from exc
