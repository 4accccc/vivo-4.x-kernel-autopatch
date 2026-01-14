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
        DebugLog.Init("patch.exe start");
        DebugLog.Write("Args: " + string.Join(" ", args));
        Console.Title = "vivo 4.x Kernel Auto Patch Tool - Preparing to Patch Kernel";
        File.WriteAllText("patch_status.log", "Fail", Encoding.UTF8);

        if (args.Length < 2 || args[1] != "-calledByMain")
        {
            Write("[!] Missing parameters for patch section (kernel file path not received)", ConsoleColor.Red);
            Write("[!] Did you run patch.exe directly?", ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] Did you run patch.exe directly?", Encoding.UTF8);
            return 1;
        }

        string targetFile = args[0];
        string r2Path = @".\radare2.exe";
        DebugLog.Write("targetFile: " + targetFile);
        DebugLog.Write("r2Path: " + r2Path);
        if (!File.Exists(targetFile))
        {
            Write("[!] Kernel file not found: " + targetFile, ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] Kernel file not found", Encoding.UTF8);
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
        Write("[*] Detecting kernel version...", ConsoleColor.Yellow);

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
            Write("[*] Detected kernel version: " + kernelVersion, ConsoleColor.Green);
            Match m2 = Regex.Match(kernelVersion, @"^([0-9]+)\.");
            if (m2.Success)
            {
                int mainVer = int.Parse(m2.Groups[1].Value);
                Write("[*] Kernel major version: " + mainVer, ConsoleColor.Cyan);
                if (mainVer != 4)
                    Write("[!] Warning: The kernel is not 4.x, compatibility is not guaranteed!", ConsoleColor.Red);
            }
        }
        else
        {
            Write("[!] Failed to detect kernel version, please verify manually if your kernel is 4.x!", ConsoleColor.Red);
        }

        Console.WriteLine();
        Write("[?] Do you want to patch vivo do_mount_check?", ConsoleColor.Yellow);
        Write("[*] Some devices do not require this patch. ", ConsoleColor.Yellow);
        Write("[*] If Magisk fails to start when not patched, please try enabling this option.", ConsoleColor.Yellow);
        Write("[*] Solution by wuxianlin.", ConsoleColor.Green);
        Write("[*] 1. Do NOT apply patch", ConsoleColor.Gray);
        Write("[*] 2. Apply patch", ConsoleColor.Gray);
        WriteInline("[*] Please enter a number (default is 1): ", ConsoleColor.Yellow);
        
        string input1 = Console.ReadLine();
        bool PATCH_C = (input1 == "2");
        
        if (PATCH_C)
            Write("[*] Selected: Patch vivo do_mount_check", ConsoleColor.Green);
        else
            Write("[*] Selected: Do NOT patch vivo do_mount_check", ConsoleColor.Yellow);

        Console.WriteLine();
        Write("[?] Do you want to attempt the mount fix?", ConsoleColor.Yellow);
        Write("[!] Please note: on some kernels, applying the mount patch may cause the device to fail to boot. If your phone won't boot after applying this patch, try choosing not to patch this address.", ConsoleColor.Yellow);
        Write("[*] 1. Do NOT apply patch", ConsoleColor.Gray);
        Write("[*] 2. Apply patch", ConsoleColor.Gray);
        WriteInline("[*] Please enter a number (default is 1): ", ConsoleColor.Yellow);
        
        string input2 = Console.ReadLine();
        bool PATCH_B = (input2 == "2");
        
        if (PATCH_B)
            Write("[*] Selected: Patch mount fix.", ConsoleColor.Green);
        else
            Write("[*] Selected: Do NOT patch mount fix.", ConsoleColor.Yellow);

        Console.Title = "vivo 4.x Kernel Auto Patch Tool - Searching for Patch Addresses";
        Console.WriteLine();
        Write("[1/2] Searching for target addresses...", ConsoleColor.Yellow);

        List<string> addressesA = new List<string>();
        RunR2(r2Path, "temp_search_a.rc", targetFile, "temp_search_a.txt");
        foreach (string line in File.ReadAllLines("temp_search_a.txt"))
        {
            Match mm = Regex.Match(line, @"(0x[0-9a-fA-F]+)");
            if (mm.Success && !addressesA.Contains(mm.Groups[1].Value))
            {
                addressesA.Add(mm.Groups[1].Value);
                Write("[*] (su) Address found !", ConsoleColor.Gray);
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
                    Write("[*] (mount fix) Address found !", ConsoleColor.Gray);
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
                    Write("[*] (do_mount_check) Address found !", ConsoleColor.Gray);
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
            Write("[!] No valid addresses found. Kernel may be unsupported, corrupted, or already patched!", ConsoleColor.Red);
            File.WriteAllText("patch_status.log", "[!] Address not found", Encoding.UTF8);
            Cleanup();
            return 1;
        }

        Console.Title = "vivo 4.x Kernel Auto Patch Tool - Applying Patches";
        Write("[2/2] Patching kernel...", ConsoleColor.Yellow);

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
            Write("[*] (su) Patching address...", ConsoleColor.Green);
        }

        if (PATCH_C && addressC != null)
        {
            sb.AppendLine("wx 0092CFC2C9CEC0DB00 @ " + addressC);
            Write("[*] (do_mount_check) Patching address...", ConsoleColor.Green);
        }

        if (PATCH_B && targetAddr != null)
        {
            sb.AppendLine("wx 081f0035 @ " + targetAddr);
            Write("[*] (mount fix) Patching address...", ConsoleColor.Green);
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
        Write("[SUCCESS] Kernel patch completed!", ConsoleColor.Green);
        Write("========================================", ConsoleColor.Cyan);
        DebugLog.Init("patch.exe stop");
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