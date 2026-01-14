using System;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Diagnostics;
using System.Collections.Generic;

class Program
{
    static int Main(string[] args)
    {
        DebugLog.Init("patch.exe 开始运行");
        DebugLog.Write("参数: " + string.Join(" ", args));
        Console.Title = "vivo 4系内核 全自动修补工具 准备修补内核";
        File.WriteAllText("patch_status.log", "Fail", Encoding.UTF8);

        if (args.Length < 2 || args[1] != "-calledByMain")
        {
            Write("[!] patch 部分缺少参数（未接收到 kernel 文件路径）", ConsoleColor.Red);
            Write("[!] 你直接运行了patch.exe？", ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] 你直接运行了patch.exe？", Encoding.UTF8);
            return 1;
        }

        string targetFile = args[0];
        string r2Path = @".\radare2.exe";
        DebugLog.Write("内核文件: " + targetFile);
        DebugLog.Write("radare2文件位置: " + r2Path);
        if (!File.Exists(targetFile))
        {
            Write("[!] 找不到 kernel 文件: " + targetFile, ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] 找不到 kernel 文件", Encoding.UTF8);
            return 1;
        }

        File.WriteAllText("temp_search_a.rc",
@"e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x .fc.0171....0054....4039.fd.0171....0054
q
", Encoding.ASCII);

        File.WriteAllText("temp_search_b.rc",
@"e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x 085040b9....0034....4039
q
", Encoding.ASCII);

        File.WriteAllText("temp_search_c.rc",
@"e asm.arch=arm
e asm.bits=64
e search.in=io.maps
oo+
s 0
/x 0092CFC2C9CDDDDA00
q
", Encoding.ASCII);

        Console.WriteLine();
        Write("[*] 正在检测内核版本...", ConsoleColor.Yellow);

        string kernelVersion = null;

        using (FileStream fs = new FileStream(targetFile, FileMode.Open, FileAccess.Read))
        {
            const int BUF_SIZE = 1024 * 1024;
            byte[] buffer = new byte[BUF_SIZE];
            int read;

            while ((read = fs.Read(buffer, 0, buffer.Length)) > 0)
            {
                string chunk = Encoding.ASCII.GetString(buffer, 0, read);
                int idx = chunk.IndexOf("Linux version ");
                if (idx >= 0)
                {
                    string sub = chunk.Substring(idx, Math.Min(128, chunk.Length - idx));
                    Match m = Regex.Match(sub, @"Linux version\s+([0-9]+\.[0-9]+\.[0-9]+[0-9A-Za-z\-\+\._]*)");
                    if (m.Success)
                    {
                        kernelVersion = m.Groups[1].Value;
                        break;
                    }
                }
            }
        }

        if (kernelVersion != null)
        {
            Write("[*] 检测到内核版本: " + kernelVersion, ConsoleColor.Green);
            Match m2 = Regex.Match(kernelVersion, @"^([0-9]+)\.");
            if (m2.Success)
            {
                int mainVer = int.Parse(m2.Groups[1].Value);
                Write("[*] 内核主版本号: " + mainVer, ConsoleColor.Cyan);
                if (mainVer != 4)
                    Write("[!] 警告：当前内核不是 4.x，可能不兼容！", ConsoleColor.Red);
            }
        }
        else
        {
            Write("[!] 未能检测到内核版本，请自行确认是否为 4.x 内核！", ConsoleColor.Red);
        }

        Console.WriteLine();
        Write("[?] 是否修补 vivo do_mount_check ？", ConsoleColor.Yellow);
        Write("[*] 部分机型不需要此修补。若此处选择不修补后 Magisk 无法启动，请选择修补后再试。", ConsoleColor.Yellow);
        Write("[*] 修补方案by wuxianlin。", ConsoleColor.Green);
        Write("[*] 1. 不修补", ConsoleColor.Gray);
        Write("[*] 2. 修补", ConsoleColor.Gray);
        WriteInline("[*] 请输入数字 (默认为 1): ", ConsoleColor.Yellow);
        
        string input1 = Console.ReadLine();
        bool PATCH_C = (input1 == "2");
        
        if (PATCH_C)
            Write("[*] 已选择：修补 vivo do_mount_check", ConsoleColor.Green);
        else
            Write("[*] 已选择：不修补 vivo do_mount_check", ConsoleColor.Yellow);

        Console.WriteLine();
        Write("[?] 是否尝试修补分区挂载？", ConsoleColor.Yellow);
        Write("[!] 部分机型修补后可能无法开机，异常请关闭该选项。", ConsoleColor.Yellow);
        Write("[*] 1. 不修补", ConsoleColor.Gray);
        Write("[*] 2. 修补", ConsoleColor.Gray);
        WriteInline("[*] 请输入数字 (默认为 1): ", ConsoleColor.Yellow);
        
        string input2 = Console.ReadLine();
        bool PATCH_B = (input2 == "2");
        
        if (PATCH_B)
            Write("[*] 已选择：修补分区挂载", ConsoleColor.Green);
        else
            Write("[*] 已选择：不修补分区挂载", ConsoleColor.Yellow);

        Console.Title = "vivo 4系内核 全自动修补工具 正在查找地址";
        Console.WriteLine();
        Write("[1/2] 正在查找地址...", ConsoleColor.Yellow);

        List<string> addressesA = new List<string>();
        RunR2(r2Path, "temp_search_a.rc", targetFile, "temp_search_a.txt");
        foreach (string line in File.ReadAllLines("temp_search_a.txt"))
        {
            Match mm = Regex.Match(line, @"(0x[0-9a-fA-F]+)");
            if (mm.Success && !addressesA.Contains(mm.Groups[1].Value))
            {
                addressesA.Add(mm.Groups[1].Value);
                Write("[*] (su) 找到地址！", ConsoleColor.Gray);
            }
        }

        string targetAddr = null;
        RunR2(r2Path, "temp_search_b.rc", targetFile, "temp_search_b.txt");
        foreach (string line in File.ReadAllLines("temp_search_b.txt"))
        {
            Match mm = Regex.Match(line, @"(0x[0-9a-fA-F]+)");
            if (mm.Success && targetAddr == null)
            {
                long addr = Convert.ToInt64(mm.Groups[1].Value.Substring(2), 16) + 4;
                targetAddr = "0x" + addr.ToString("x");
                if (PATCH_B)
                    Write("[*] (mount fix) 找到地址！", ConsoleColor.Gray);
                break;
            }
        }

        string addressC = null;
        RunR2(r2Path, "temp_search_c.rc", targetFile, "temp_search_c.txt");
        foreach (string line in File.ReadAllLines("temp_search_c.txt"))
        {
            Match mm = Regex.Match(line, @"(0x[0-9a-fA-F]+)");
            if (mm.Success)
            {
                addressC = mm.Groups[1].Value;
                if (PATCH_C)
                    Write("[*] (do_mount_check) 找到地址！", ConsoleColor.Gray);
                break;
            }
        }

        DebugLog.Write("temp_search_a.txt:\r\n" + File.ReadAllText("temp_search_a.txt"));
        DebugLog.Write("temp_search_b.txt:\r\n" + File.ReadAllText("temp_search_b.txt"));
        DebugLog.Write("temp_search_c.txt:\r\n" + File.ReadAllText("temp_search_c.txt"));

        bool doPatchA = (addressesA.Count > 0);
        bool doPatchB = (PATCH_B && targetAddr != null);
        bool doPatchC = (PATCH_C && addressC != null);

        if (!doPatchA && !doPatchB && !doPatchC)
        {
            Write("[!] 没有找到对应地址，可能是内核不支持、内核损坏或者内核已经被修补过了！", ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] 没有找到对应地址", Encoding.UTF8);
            Cleanup();
            return 1;
        }

        Console.Title = "vivo 4系内核 全自动修补工具 正在修补内核";
        Write("[2/2] 正在修补...", ConsoleColor.Yellow);

        StringBuilder sb = new StringBuilder();
        sb.AppendLine("e asm.arch=arm");
        sb.AppendLine("e asm.bits=64");
        sb.AppendLine("e io.cache=false");
        sb.AppendLine("e search.in=io.maps");
        sb.AppendLine("oo+");
        sb.AppendLine();

        foreach (string a in addressesA)
        {
            sb.AppendLine("wx 3fdd0071 @ " + a);
            Write("[*] (su) 修补地址...", ConsoleColor.Green);
        }

        if (PATCH_C && addressC != null)
        {
            sb.AppendLine("wx 0092CFC2C9CEC0DB00 @ " + addressC);
            Write("[*] (do_mount_check) 修补地址...", ConsoleColor.Green);
        }

        if (PATCH_B && targetAddr != null)
        {
            sb.AppendLine("wx 081f0035 @ " + targetAddr);
            Write("[*] (mount fix) 修补地址...", ConsoleColor.Green);
        }

        sb.AppendLine("wc");
        sb.AppendLine("q");

        File.WriteAllText("temp_apply_patch.rc", sb.ToString(), Encoding.ASCII);
        DebugLog.Write("temp_apply_patch.rc:\r\n" + sb.ToString());
        RunR2Apply(r2Path, "temp_apply_patch.rc", targetFile);

        Cleanup();
        File.WriteAllText("patch_status.log", "SUCCESS", Encoding.UTF8);

        Console.WriteLine();
        Write("========================================", ConsoleColor.Cyan);
        Write("[SUCCESS] 内核自动修补完成！", ConsoleColor.Green);
        Write("========================================", ConsoleColor.Cyan);
        DebugLog.Init("patch.exe 结束运行");
        
        return 0;
    }

    static void RunR2(string r2, string rc, string target, string output)
    {
        Process p = new Process();
        p.StartInfo = new ProcessStartInfo(r2, "-qi " + rc + " \"" + target + "\"");
        p.StartInfo.UseShellExecute = false;
        p.StartInfo.RedirectStandardOutput = true;
        p.StartInfo.RedirectStandardError = true;
        p.StartInfo.CreateNoWindow = true;
        p.Start();
        string txt = p.StandardOutput.ReadToEnd() + p.StandardError.ReadToEnd();
        p.WaitForExit();
        File.WriteAllText(output, txt);
    }

    static void RunR2Apply(string r2, string rc, string target)
    {
        Process p = Process.Start(new ProcessStartInfo(r2, "-w -q -i " + rc + " \"" + target + "\"")
        {
            UseShellExecute = false,
            CreateNoWindow = true
        });
        p.WaitForExit();
    }

    static void Cleanup()
    {
        foreach (string f in Directory.GetFiles(".", "temp_*"))
            try { File.Delete(f); } catch { }
    }

    static void WriteInline(string s, ConsoleColor c)
    {
        var old = Console.ForegroundColor;
        Console.ForegroundColor = c;
        Console.Write(s);
        Console.ForegroundColor = old;
        Console.Out.Flush();
    }

    static void Write(string s, ConsoleColor c)
    {
        var old = Console.ForegroundColor;
        Console.ForegroundColor = c;
        Console.WriteLine(s);
        Console.ForegroundColor = old;
    }

    static class DebugLog
    {
#if DEBUG
        static readonly object _lock = new object();
        static string LogFile = null;
        static bool LogEnabled = false;

        public static void Init(string title)
        {
            lock (_lock)
            {
                if (LogEnabled && LogFile != null)
                {
                    try
                    {
                        File.AppendAllText(LogFile, "\r\n========== " + title + " ==========\r\n");
                    }
                    catch { }
                    return;
                }

                try
                {
                    string desktopPath = Environment.GetFolderPath(Environment.SpecialFolder.Desktop);
                    LogFile = Path.Combine(desktopPath, "debug.log");
                    File.AppendAllText(LogFile, "");
                    LogEnabled = true;
                    File.AppendAllText(LogFile, "\r\n========== " + title + " ==========\r\n");
                }
                catch
                {
                    try
                    {
                        LogFile = @"C:\debug.log";
                        File.AppendAllText(LogFile, "");
                        LogEnabled = true;
                        File.AppendAllText(LogFile, "\r\n========== " + title + " ==========\r\n");
                    }
                    catch
                    {
                        LogEnabled = false;
                    }
                }
            }
        }

        public static void Write(string msg)
        {
            if (!LogEnabled) return;
            try
            {
                lock (_lock)
                {
                    File.AppendAllText(LogFile, "[" + DateTime.Now.ToString("HH:mm:ss.fff") + "] " + msg + "\r\n");
                }
            }
            catch { }
        }

        public static void WriteException(Exception ex)
        {
            Write("EXCEPTION: " + ex);
        }
#else
        public static void Init(string t) { }
        public static void Write(string m) { }
        public static void WriteException(Exception e) { }
#endif
    }
}