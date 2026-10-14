# -*- coding: utf-8 -*-
"""把传输代码导入已生成的工作簿。Excel 不允许外部直接写 VBA 工程时，走编辑器的导入命令。"""
import os
import sys
import time
import zipfile
from pathlib import Path

import win32com.client

LOG = Path(__file__).resolve().parent / "_inject.log"


def load_gui():
    global win32clipboard, win32con, win32gui
    import win32clipboard
    import win32con
    import win32gui


def log(message):
    print(message, flush=True)
    with LOG.open("a", encoding="utf-8") as handle:
        handle.write(message + "\n")


ROOT = Path(__file__).resolve().parent
XLSX = ROOT / "_传输.xlsx"
XLSM = ROOT / "传输.xlsm"
BAS_SRC = ROOT / "传输代码.bas"
JSON_SRC = ROOT / "JsonConverter.bas"
BAS = Path(os.environ["TEMP"]) / "TransferBook.bas"
JSON_BAS = Path(os.environ["TEMP"]) / "JsonConverter.bas"
SCRRUN = "{420B2830-E718-11CF-893D-00A0C9054228}"


def prepare_bas():
    write_bas(BAS_SRC, BAS)
    write_bas(JSON_SRC, JSON_BAS)


def write_bas(source, target):
    text = source.read_text(encoding="utf-8")
    text = text.replace("\r\n", "\n").replace("\n", "\r\n")
    target.write_bytes(text.encode("gbk"))


def ensure_scrrun(workbook):
    references = workbook.VBProject.References
    for ref in references:
        if str(ref.GUID).upper() == SCRRUN.upper():
            return
    references.AddFromGuid(SCRRUN, 1, 0)


def remove_module(workbook, name):
    components = workbook.VBProject.VBComponents
    for index in range(components.Count, 0, -1):
        component = components.Item(index)
        if component.Type == 1 and component.Name == name:
            components.Remove(component)


def install_modules(workbook):
    ensure_scrrun(workbook)
    remove_module(workbook, "传输")
    remove_module(workbook, "JsonConverter")
    workbook.VBProject.VBComponents.Import(str(JSON_BAS))
    workbook.VBProject.VBComponents.Import(str(BAS))


def titles():
    found = []

    def visit(hwnd, _):
        if win32gui.IsWindowVisible(hwnd):
            title = win32gui.GetWindowText(hwnd)
            if title:
                found.append((hwnd, title, win32gui.GetClassName(hwnd)))

    win32gui.EnumWindows(visit, None)
    return found


def focus(hwnd):
    user32 = __import__("ctypes").windll.user32
    user32.keybd_event(0x12, 0, 0, 0)
    user32.keybd_event(0x12, 0, 2, 0)
    win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    win32gui.SetForegroundWindow(hwnd)
    time.sleep(0.4)


def window_info(hwnd):
    try:
        return win32gui.GetWindowText(hwnd), win32gui.GetClassName(hwnd)
    except Exception:
        return "", ""


def foreground():
    hwnd = win32gui.GetForegroundWindow()
    title, klass = window_info(hwnd)
    return hwnd, title, klass


def find_window(predicate):
    for hwnd, title, klass in titles():
        if predicate(title, klass):
            return hwnd, title, klass
    return None


def wait_window(predicate, timeout):
    end = time.time() + timeout
    while time.time() < end:
        found = find_window(predicate)
        if found:
            return found
        time.sleep(0.2)
    shown = [(title, klass) for _, title, klass in titles()]
    raise RuntimeError(f"等待窗口超时：{shown}")


def set_clip(text):
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text)
    finally:
        win32clipboard.CloseClipboard()


def main():
    load_gui()
    if LOG.exists():
        LOG.unlink()
    log("start")
    prepare_bas()
    log("bas")
    excel = win32com.client.DispatchEx("Excel.Application")
    log("excel")
    excel.Visible = True
    excel.DisplayAlerts = False
    excel.AutomationSecurity = 1
    shell = win32com.client.Dispatch("WScript.Shell")
    wb = None
    try:
        wb = excel.Workbooks.Open(str(XLSX))
        log("opened")
        excel_hwnd = None
        for hwnd, title, klass in titles():
            if klass == "XLMAIN":
                excel_hwnd = hwnd
                break
        if excel_hwnd is None:
            raise RuntimeError("没有找到 Excel 窗口")
        focus(excel_hwnd)
        excel.SendKeys("{ESC}")
        time.sleep(0.3)
        excel.SendKeys("%{F11}")
        try:
            vbe_hwnd, vbe_title, _ = wait_window(
                lambda title, klass: "Visual Basic" in title or "VBA" in title,
                4,
            )
        except RuntimeError:
            excel.SendKeys("{ESC}")
            time.sleep(0.2)
            focus(excel_hwnd)
            excel.SendKeys("%{F11}")
            vbe_hwnd, vbe_title, _ = wait_window(
                lambda title, klass: "Visual Basic" in title or "VBA" in title,
                8,
            )
        log(f"VBE {vbe_title}")
        focus(vbe_hwnd)
        shell.SendKeys("%fi")
        dialog_hwnd, dialog_title, dialog_class = wait_window(
            lambda title, klass: klass == "#32770",
            8,
        )
        log(f"DIALOG {dialog_title}")
        edit = None
        button = None
        controls = []

        def child(hwnd, _):
            nonlocal edit, button
            title, klass = window_info(hwnd)
            controls.append(f"{klass}:{title}")
            if klass == "Edit" and edit is None:
                edit = hwnd
            if klass == "Button" and ("打开" in title or title.startswith("Open")):
                button = hwnd

        win32gui.EnumChildWindows(dialog_hwnd, child, None)
        log("CONTROLS " + " | ".join(controls))
        if edit is None or button is None:
            raise RuntimeError("导入对话框里没有文件名或打开按钮")
        user32 = __import__("ctypes").windll.user32
        user32.SendMessageW(edit, 0x000C, 0, str(BAS))
        user32.SendMessageW(button, 0x00F5, 0, 0)
        end = time.time() + 15
        closed = False
        while time.time() < end:
            _, title, klass = foreground()
            if klass != "#32770":
                closed = True
                break
            time.sleep(0.3)
        if not closed:
            _, title, klass = foreground()
            log(f"DIALOG_STILL {title} {klass}")
            raise RuntimeError("导入对话框没有关闭")
        log(f"AFTER {foreground()}")
        focus(vbe_hwnd)
        shell.SendKeys("%q")
        wait_window(lambda title, klass: klass == "XLMAIN", 8)
        if XLSM.exists():
            XLSM.unlink()
        wb.SaveAs(str(XLSM), 52)
        wb.Close(False)
        wb = None
        excel.Quit()
        time.sleep(1)
        with zipfile.ZipFile(XLSM) as book:
            names = book.namelist()
            log("PARTS " + str([name for name in names if "vba" in name.lower() or name.endswith("workbook.xml")]))
            if "xl/vbaProject.bin" not in names:
                raise RuntimeError("导入后工作簿里没有宏工程")
            blob = book.read("xl/vbaProject.bin")
            log(f"BIN {len(blob)} {('登录'.encode('gbk') in blob)}")
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 1
        wb = excel.Workbooks.Open(str(XLSM))
        excel.Run("自检")
        log("SELFTEST_OK")
        info = wb.Worksheets("使用说明")
        if info.Buttons().Count > 0:
            log("buttons kept")
            wb.Save()
            wb.Close(False)
            wb = None
            log(str(XLSM))
            return
        buttons = [
            (220, 18, 90, 28, "登录", "登录"),
            (320, 18, 140, 28, "导入当前工作表", "导入当前工作表"),
            (470, 18, 150, 28, "按顺序导入全部", "按顺序导入全部"),
            (630, 18, 140, 28, "从入库载入", "从入库载入"),
        ]
        for left, top, width, height, caption, macro in buttons:
            button = info.Buttons().Add(left, top, width, height)
            button.Caption = caption
            button.OnAction = macro
        wb.Save()
        wb.Close(False)
        wb = None
        log(str(XLSM))
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            excel.Quit()
        except Exception:
            pass


def click_yes_if_present():
    found = find_window(lambda title, klass: klass == "#32770")
    if not found:
        return
    dialog_hwnd, title, _ = found
    log(f"REPLACE {title}")
    yes = None

    def child(hwnd, _):
        nonlocal yes
        text, klass = window_info(hwnd)
        if klass == "Button" and (text.startswith("是") or text.startswith("Yes")):
            yes = hwnd

    win32gui.EnumChildWindows(dialog_hwnd, child, None)
    if yes is None:
        return
    __import__("ctypes").windll.user32.SendMessageW(yes, 0x00F5, 0, 0)
    end = time.time() + 8
    while time.time() < end and find_window(lambda title, klass: klass == "#32770"):
        time.sleep(0.2)


def patch_existing():
    load_gui()
    for hwnd, title, klass in titles():
        if "WPS" in title or "传输111" in title:
            win32gui.ShowWindow(hwnd, 6)
    prepare_bas()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = True
    excel.DisplayAlerts = False
    excel.AutomationSecurity = 1
    shell = win32com.client.Dispatch("WScript.Shell")
    wb = None
    try:
        wb = excel.Workbooks.Open(str(XLSM))
        excel_hwnd = None
        for hwnd, title, klass in titles():
            if klass == "XLMAIN":
                excel_hwnd = hwnd
                break
        if excel_hwnd is None:
            raise RuntimeError("没有找到 Excel 窗口")
        focus(excel_hwnd)
        excel.CommandBars.ExecuteMso("VisualBasic")
        try:
            vbe_hwnd, _, _ = wait_window(lambda title, klass: "Visual Basic" in title and "传输111" not in title, 8)
        except RuntimeError:
            focus(excel_hwnd)
            excel.CommandBars.ExecuteMso("VisualBasic")
            vbe_hwnd, _, _ = wait_window(lambda title, klass: "Visual Basic" in title and "传输111" not in title, 8)
        focus(vbe_hwnd)
        shell.SendKeys("%fi")
        dialog_hwnd, _, _ = wait_window(lambda title, klass: klass == "#32770", 8)
        edit = None
        button = None

        def child(hwnd, _):
            nonlocal edit, button
            text, klass = window_info(hwnd)
            if klass == "Edit" and edit is None:
                edit = hwnd
            if klass == "Button" and ("打开" in text or text.startswith("Open")):
                button = hwnd

        win32gui.EnumChildWindows(dialog_hwnd, child, None)
        user32 = __import__("ctypes").windll.user32
        user32.SendMessageW(edit, 0x000C, 0, str(BAS))
        user32.SendMessageW(button, 0x00F5, 0, 0)
        time.sleep(0.8)
        click_yes_if_present()
        end = time.time() + 10
        while time.time() < end and find_window(lambda title, klass: klass == "#32770"):
            click_yes_if_present()
            time.sleep(0.3)
        focus(vbe_hwnd)
        shell.SendKeys("%q")
        wait_window(lambda title, klass: klass == "XLMAIN", 8)
        wb.Save()
        wb.Close(False)
        wb = None
        excel.Quit()
        time.sleep(1)
        excel = win32com.client.DispatchEx("Excel.Application")
        excel.Visible = False
        excel.DisplayAlerts = False
        excel.AutomationSecurity = 1
        wb = excel.Workbooks.Open(str(XLSM))
        excel.Run("自检")
        log("SELFTEST_OK")
        wb.Close(False)
        wb = None
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            excel.Quit()
        except Exception:
            pass


def install_existing():
    if LOG.exists():
        LOG.unlink()
    log("install")
    prepare_bas()
    excel = win32com.client.DispatchEx("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False
    excel.AutomationSecurity = 1
    wb = None
    try:
        wb = excel.Workbooks.Open(str(XLSM))
        log("opened")
        install_modules(wb)
        log("imported")
        excel.Run("自检")
        log("SELFTEST_OK")
        wb.Save()
        wb.Close(False)
        wb = None
        log(str(XLSM))
    except Exception as exc:
        log(f"FAIL {type(exc).__name__}: {exc}")
        raise
    finally:
        try:
            if wb is not None:
                wb.Close(False)
        except Exception:
            pass
        try:
            excel.Quit()
        except Exception:
            pass


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "patch":
        patch_existing()
    elif len(sys.argv) > 1 and sys.argv[1] == "modules":
        install_existing()
    else:
        main()
