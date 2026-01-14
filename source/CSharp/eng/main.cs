using System;
using System.IO;
using System.Diagnostics;
using System.Text;
using System.Threading;
using System.Globalization;
using System.Management;
using System.Security.Cryptography;

class Program
{
    static void Main(string[] args)
    {
#if DEBUG
        SuppressCtrlCUnhandledException();
#endif
        RegisterExitHandlers();
        DebugLog.Init("main.exe start");
        DebugLog.WriteSystemInfo();
        DebugLog.Write("Args: " + string.Join(" ", args));

        if (IsReactOS())
        {
            WriteRed("==================================================================");
            WriteRed("[!] Detected ReactOS environment");
            WriteRed("[!] This tool does NOT support running on ReactOS");
            WriteRed("[!] ReactOS is not a fully compatible Windows implementation");
            WriteRed("[!] Please use a real Windows system or Wine on Linux");
            WriteRed("==================================================================");
            Console.WriteLine();
            Console.Write("Press Enter to exit...");
            Console.ReadLine();
            Environment.Exit(1);
        }

        if (IsRunningInWine())
        {
            WriteYellow("========================================================================");
            WriteYellow("[!] Detected program running in a Wine container.");
            WriteYellow("[*] Drive letters can be found at: ~/.wine/dosdevices/");
            WriteYellow("[*] Or check: /home/[username]/.wine/dosdevices/");
            WriteYellow("========================================================================");
            Console.WriteLine();
        }

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Please enter boot.img path";

#if DEBUG
        WriteRed("WARNING: This is Debug Build. debug.log will be written to user Desktop.");
#endif

        WriteCyan("========================================================================");
        WriteCyan("               vivo 4.x Kernel Auto-Patch Tool");
        WriteCyan("              Tool Author: MyAngelAnchorage");
        WriteCyan("      Repository: https://github.com/4accccc/vivo-4.x-kernel-autopatch");
        WriteCyan("                   Solution Provider: romanovj");
        WriteCyan("========================================================================");

        string MagiskBoot = @".\magiskboot.exe";
        string PatchEXE = @".\patch.exe";

        if (!File.Exists(MagiskBoot))
            Fatal("[!] magiskboot.exe not found. Aborting.");

        if (!File.Exists(PatchEXE))
            Fatal("[!] patch.exe not found. Aborting.");

        Console.Write("[*] Please enter the full path of boot.img (e.g. D:\\boot.img), preferably without quotes!");
        string BootImg = Console.ReadLine().Trim('"');

        if (string.IsNullOrWhiteSpace(BootImg))
            Fatal("[!] No boot.img entered. Aborting.");

        if (!File.Exists(BootImg))
            Fatal("[!] boot.img does not exist. Aborting.");

        if ((File.GetAttributes(BootImg) & FileAttributes.Directory) != 0)
            Fatal("[!] Input is a folder, not a file. Aborting.");

        WriteGreen(string.Format("[*] Confirmed boot.img: {0}", BootImg));

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Enter output path for patched boot.img";

        Console.Write("[*] Enter the full save path for the patched boot.img (leave blank = same folder as boot.img), preferably without quotes!");
        string UserSave = Console.ReadLine().Trim('"');

        string BootDir = Path.GetDirectoryName(BootImg);
        string FallbackPath = Path.Combine(BootDir, "patched-boot.img");
        string FinalOutputPath = FallbackPath;

        if (!string.IsNullOrWhiteSpace(UserSave))
        {
            try
            {
                UserSave = UserSave.TrimEnd('\\', '/');
                
                if (UserSave.Length == 2 && UserSave[1] == ':')
                {
                    UserSave += Path.DirectorySeparatorChar;
                }
                
                if (Directory.Exists(UserSave))
                {
                    FinalOutputPath = Path.Combine(UserSave, "patched-boot.img");
                }
                else if (File.Exists(UserSave))
                {
                    WriteYellow("[!] File already exist. Will be overwritten.");
                    FinalOutputPath = UserSave;
                }
                else
                {
                    string dir = Path.GetDirectoryName(UserSave);
                    
                    if (string.IsNullOrEmpty(dir))
                        dir = ".";
                    
                    if (!Directory.Exists(dir))
                        throw new Exception();

                    string test = Path.Combine(dir, ".__write_test__.tmp");
                    File.WriteAllText(test, "test");
                    File.Delete(test);

                    FinalOutputPath = UserSave;
                }
            }
            catch
            {
                WriteYellow("[!] Specified path is not writable. Saving to boot.img folder.");
                FinalOutputPath = FallbackPath;
            }
        }
        else
        {
            WriteYellow("[*] No output path entered. Saving to boot.img folder.");
            FinalOutputPath = FallbackPath;
        }

        try
        {
            string finalDir = Path.GetDirectoryName(Path.GetFullPath(FinalOutputPath));
            if (string.IsNullOrEmpty(finalDir)) finalDir = ".";
            
            string finalTest = Path.Combine(finalDir, ".__final_check__.tmp");
            File.WriteAllText(finalTest, "test");
            File.Delete(finalTest);
        }
        catch
        {
            Fatal("[!] The fallback output directory is not writable! Please check folder permissions!");
        }

        DebugLog.Write("BootImg input: " + BootImg);
        DebugLog.Write("UserSave input: " + UserSave);
        DebugLog.Write("FinalOutputPath: " + FinalOutputPath);

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Unpacking boot.img";
        WriteYellow("[*] Unpacking boot.img ...");
        Run(MagiskBoot, string.Format("unpack \"{0}\"", BootImg), "unpack_log.txt");

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Searching for kernel file";

        string[] kernelCandidates = { "kernel", "kernel.gz", "kernel.lz4", "kernel.lzma", "Image", "zImage", "Image.gz" };
        string KernelFile = null;
        foreach (var k in kernelCandidates)
        {
            if (File.Exists(k))
            {
                KernelFile = k;
                break;
            }
        }

        if (KernelFile == null)
            Fatal("[!] Kernel file not found.");

        if (KernelFile.EndsWith(".gz") || KernelFile.EndsWith(".lz4") || KernelFile.EndsWith(".lzma"))
        {
            WriteYellow(string.Format("[*] Compressed kernel detected: {0} , decompressing...", KernelFile));
            Run(MagiskBoot, string.Format("decompress \"{0}\" kernel_decompressed", KernelFile), null);

            if (!File.Exists("kernel_decompressed"))
                Fatal("[!] Decompression failed.");

            KernelFile = "kernel_decompressed";
        }

        WriteGreen("[+] Kernel file: " + KernelFile);
        string kernelHashBefore = CalcSHA256(KernelFile);
        if (kernelHashBefore == null)
            WriteRed("[!] Can't calculate Kernel SHA256 before patch!");

        DebugLog.Write("Kernel SHA256 (before patch): " + kernelHashBefore);
        WriteYellow("[*] Patching kernel...");

        Run(PatchEXE, string.Format("\"{0}\" -calledByMain", KernelFile), null);
        string kernelHashAfter = CalcSHA256(KernelFile);
        if (kernelHashAfter == null)
            WriteRed("[!] Can't calculate Kernel SHA256 after patch!");

        DebugLog.Write("Kernel SHA256 (after patch): " + kernelHashAfter);
        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Kernel patched";

        string status = File.Exists("patch_status.log") ? File.ReadAllText("patch_status.log") : "Fail";

        if (status.Contains("Address not found"))
            FailStatus("[Failed] Patch failed: no matching address found.");

        if (status.Contains("Kernel file not found"))
            FailStatus("[Failed] Kernel file not found by patcher.");

        if (status.Contains("run patch.exe directly"))
            FailStatus("[Failed] Parameter mismatch.");

        if (!status.Contains("SUCCESS"))
            FailStatus("[Failed] Kernel patch did not succeed (unknown reason).");

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Repacking boot.img";
        WriteYellow("[*] Patch succeeded. Repacking boot.img ...");
        Run(MagiskBoot, string.Format("repack \"{0}\"", BootImg), "repack_log.txt");

        if (!File.Exists("new-boot.img"))
            Fatal("[!] Repacking boot.img failed!");

        Thread.Sleep(300);
        DebugLog.Write("Copy new-boot.img -> patched-boot.img");
        File.Copy("new-boot.img", "patched-boot.img", true);

        DebugLog.Write("Copy patched-boot.img -> " + FinalOutputPath);
        File.Copy("patched-boot.img", FinalOutputPath, true);

        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Completed";
        Console.WriteLine("========================================================================");
        WriteGreen("                    [SUCCESS] ");
        WriteGreen("Patched boot.img bypassing SU restrictions has been repacked.");
        WriteGreen("Please manually use the generated boot.img in Magisk!");
        WriteGreen("Output Path: " + FinalOutputPath);
        WriteYellow("Please note: We have found that on some models, in addition to kernel");
        WriteYellow("restrictions, SELinux also imposes certain limitations.");
        WriteYellow("This tool does not make any modifications related to SELinux.");
        Console.WriteLine("========================================================================");

        Console.Write("Press Enter to exit...");
        Console.ReadLine();
        CleanupAndSelfDelete();
        Environment.Exit(0);
    }

    static void WriteColored(string line)
    {
        if (line != null && line.Length == 0)
        {
            Console.WriteLine();
            return;
        }

        bool inline = false;
        if (line.StartsWith("[[INLINE]]"))
        {
            inline = true;
            line = line.Substring(10);
        }

        if (line == "[[GREEN]]" || line == "[[YELLOW]]" || line == "[[CYAN]]" || line == "[[RED]]" || line == "[[GRAY]]")
            return;

        ConsoleColor color = ConsoleColor.Gray;

        if (line.StartsWith("[[GREEN]]"))
        {
            color = ConsoleColor.Green;
            line = line.Substring(9);
        }
        else if (line.StartsWith("[[YELLOW]]"))
        {
            color = ConsoleColor.Yellow;
            line = line.Substring(10);
        }
        else if (line.StartsWith("[[CYAN]]"))
        {
            color = ConsoleColor.Cyan;
            line = line.Substring(8);
        }
        else if (line.StartsWith("[[RED]]"))
        {
            color = ConsoleColor.Red;
            line = line.Substring(7);
        }
        else if (line.StartsWith("[[GRAY]]"))
        {
            color = ConsoleColor.Gray;
            line = line.Substring(8);
        }

        var old = Console.ForegroundColor;
        Console.ForegroundColor = color;

        if (inline)
            Console.Write(line);
        else
            Console.WriteLine(line);

        Console.ForegroundColor = old;
    }

    static string CalcSHA256(string file)
    {
        try
        {
            using (var fs = File.OpenRead(file))
            using (var sha = SHA256.Create())
            {
                byte[] hash = sha.ComputeHash(fs);
                StringBuilder sb = new StringBuilder(hash.Length * 2);
                foreach (byte b in hash)
                    sb.Append(b.ToString("x2"));
                return sb.ToString();
            }
        }
        catch (Exception ex)
        {
            DebugLog.WriteException(ex);
            return null;
        }
    }

    static void Run(string exe, string args, string log)
    {
        DebugLog.Write("Run exe: " + exe);
        DebugLog.Write("Run args: " + args);

        bool isPatch = Path.GetFileName(exe)
            .Equals("patch.exe", StringComparison.OrdinalIgnoreCase);

        var psi = new ProcessStartInfo(exe, args);

        if (isPatch)
        {
            DebugLog.Write("Run patch.exe attached to current console");

            psi.UseShellExecute = false;
            psi.RedirectStandardInput = false;
            psi.RedirectStandardOutput = false;
            psi.RedirectStandardError = false;
            psi.CreateNoWindow = false;

            var p = Process.Start(psi);
            p.WaitForExit();

            DebugLog.Write("patch.exe exit code: " + p.ExitCode);
            return;
        }

        if (log == null)
        {
            psi.UseShellExecute = false;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.CreateNoWindow = true;

            var p = Process.Start(psi);

            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    string line;
                    while ((line = p.StandardOutput.ReadLine()) != null)
                    {
                        WriteColored(line);
                        DebugLog.Write("[magiskboot][stdout] " + line);
                    }
                }
                catch { }
            });

            ThreadPool.QueueUserWorkItem(_ =>
            {
                try
                {
                    string line;
                    while ((line = p.StandardError.ReadLine()) != null)
                    {
                        WriteColored(line);
                        DebugLog.Write("[magiskboot][stderr] " + line);
                    }
                }
                catch { }
            });

            p.WaitForExit();
        }
        else
        {
            psi.UseShellExecute = false;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            psi.CreateNoWindow = true;

            var p = Process.Start(psi);
            string output = p.StandardOutput.ReadToEnd();
            string error  = p.StandardError.ReadToEnd();
            p.WaitForExit();

            File.WriteAllText(log, output + error, Encoding.UTF8);

            DebugLog.Write("[magiskboot][stdout]\r\n" + output);
            if (!string.IsNullOrEmpty(error))
                DebugLog.Write("[magiskboot][stderr]\r\n" + error);
        }
    }

    static void Fatal(string msg)
    {
        WriteRed(msg);
        Console.Write("Press Enter to exit...");
        Console.ReadLine();
        CleanupAndSelfDelete();
        Environment.Exit(1);
    }

    static void FailStatus(string msg)
    {
        Console.Title = "vivo 4.x Kernel Auto-Patch Tool  Patch Failed";
        WriteRed("===============================================");
        WriteRed(msg);
        WriteRed("===============================================");
        Console.Write("Press Enter to exit...");
        Console.ReadLine();
        CleanupAndSelfDelete();
        Environment.Exit(1);
    }

    static void CleanupAndSelfDelete()
    {
        try
        {
            string exePath = Process.GetCurrentProcess().MainModule.FileName;
            string workDir = Path.GetDirectoryName(exePath);

            string cmd = string.Format(
                "/c ping 127.0.0.1 -n 3 > nul & rmdir /s /q \"{0}\"",
                workDir
            );

            Process.Start(new ProcessStartInfo
            {
                FileName = "cmd.exe",
                Arguments = cmd,
                UseShellExecute = false,
                CreateNoWindow = true,
                WindowStyle = ProcessWindowStyle.Hidden
            });
        }
        catch (Exception ex)
        {
            DebugLog.WriteException(ex);
        }
    }

    static void TryDelete(string path)
    {
        TryDelete(path, false);
    }

    static void TryDelete(string path, bool dir)
    {
        try
        {
            if (dir) Directory.Delete(path, true);
            else File.Delete(path);
        }
        catch { }
    }

    static void WriteCyan(string s) { WriteColor(s, ConsoleColor.Cyan); }
    static void WriteGreen(string s) { WriteColor(s, ConsoleColor.Green); }
    static void WriteYellow(string s) { WriteColor(s, ConsoleColor.Yellow); }
    static void WriteRed(string s) { WriteColor(s, ConsoleColor.Red); }

    static void WriteColor(string s, ConsoleColor c)
    {
        var old = Console.ForegroundColor;
        Console.ForegroundColor = c;
        Console.WriteLine(s);
        Console.ForegroundColor = old;
    }

    static bool IsReactOS()
    {
        try
        {
            string os = Environment.OSVersion.VersionString;
            if (!string.IsNullOrEmpty(os) &&
                os.IndexOf("ReactOS", StringComparison.OrdinalIgnoreCase) >= 0)
            {
                DebugLog.Write("Detected ReactOS (OSVersion): " + os);
                return true;
            }

            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\ReactOS"))
                {
                    if (key != null)
                    {
                        DebugLog.Write("Detected ReactOS (HKLM\\SOFTWARE\\ReactOS)");
                        return true;
                    }
                }
            }
            catch { }

            return false;
        }
        catch (Exception ex)
        {
            DebugLog.WriteException(ex);
            return false;
        }
    }

    static bool IsRunningInWine()
    {
        try
        {
            string[] wineEnvVars = { "WINE", "WINEPREFIX", "WINEARCH", "WINELOADER" };
            foreach (string envVar in wineEnvVars)
            {
                if (!string.IsNullOrEmpty(Environment.GetEnvironmentVariable(envVar)))
                {
                    DebugLog.Write("Wine detected via environment variable: " + envVar);
                    return true;
                }
            }

            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"Software\Wine"))
                {
                    if (key != null)
                    {
                        DebugLog.Write("Wine detected via registry key");
                        return true;
                    }
                }
            }
            catch { }

            try
            {
                IntPtr hModule = GetModuleHandle("ntdll.dll");
                if (hModule != IntPtr.Zero)
                {
                    IntPtr wineFunc = GetProcAddress(hModule, "wine_get_version");
                    if (wineFunc != IntPtr.Zero)
                    {
                        DebugLog.Write("Wine detected via wine_get_version function");
                        return true;
                    }
                }
            }
            catch { }

            return false;
        }
        catch (Exception ex)
        {
            DebugLog.WriteException(ex);
            return false;
        }
    }

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Ansi)]
    static extern IntPtr GetModuleHandle(string lpModuleName);

    [System.Runtime.InteropServices.DllImport("kernel32.dll", CharSet = System.Runtime.InteropServices.CharSet.Ansi)]
    static extern IntPtr GetProcAddress(IntPtr hModule, string lpProcName);

    delegate bool ConsoleCtrlDelegate(CtrlTypes ctrlType);

    [System.Runtime.InteropServices.DllImport("kernel32.dll")]
    static extern bool SetConsoleCtrlHandler(ConsoleCtrlDelegate handler, bool add);

    static ConsoleCtrlDelegate _handler = ConsoleCtrlHandler;

    enum CtrlTypes
    {
        CTRL_C_EVENT = 0,
        CTRL_BREAK_EVENT = 1,
        CTRL_CLOSE_EVENT = 2,
        CTRL_LOGOFF_EVENT = 5,
        CTRL_SHUTDOWN_EVENT = 6
    }

    static bool _exiting = false;

#if DEBUG
    static void SuppressCtrlCUnhandledException()
    {
        AppDomain.CurrentDomain.UnhandledException += (sender, e) =>
        {
            try
            {
            }
            catch
            {
            }
        };
    }
#endif

    static void RegisterExitHandlers()
    {
        Console.CancelKeyPress += (sender, e) =>
        {
            if (_exiting) return;
            _exiting = true;

            e.Cancel = true;
            DebugLog.Write("Ctrl+C / Ctrl+Break captured!");

            CleanupAndSelfDelete();
            Environment.Exit(1);
        };

        SetConsoleCtrlHandler(ConsoleCtrlHandler, true);
    }

    static bool ConsoleCtrlHandler(CtrlTypes ctrlType)
    {
        if (_exiting) return false;
        _exiting = true;

        DebugLog.Write("Console control signal received: " + ctrlType);

        CleanupAndSelfDelete();
        Environment.Exit(1);

        return false;
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
                        WriteYellow("WARNING: This is Debug Build. debug.log will be written to C:\\ root directory.");
                        File.AppendAllText(LogFile, "\r\n========== " + title + " ==========\r\n");
                    }
                    catch
                    {
                        LogEnabled = false;
                        WriteRed("WARNING: This is Debug Build. debug.log cannot be created on user Desktop or system drive root, please check permissions.");
                    }
                }
            }
        }

        public static void WriteSystemInfo()
        {
            if (!LogEnabled) return;
            
            try
            {
                Write("===== System Information =====");
                Write("OS: " + Environment.OSVersion.VersionString);
                Write("OS Platform: " + Environment.OSVersion.Platform);
                Write("OS Version: " + Environment.OSVersion.Version);
                Write("System Language: " + CultureInfo.CurrentCulture.Name);
                Write("UI Language: " + CultureInfo.CurrentUICulture.Name);
                Write("64-bit OS: " + Environment.Is64BitOperatingSystem);
                Write("64-bit Process: " + Environment.Is64BitProcess);
                Write("CPU: " + GetCpuName());
                Write("Memory: " + GetMemoryInfo());
                Write("Is Virtual Machine: " + GetVirtualMachineInfo());
                Write("================================");
            }
            catch (Exception ex)
            {
                Write("WriteSystemInfo failed: " + ex);
            }
        }

        static string GetCpuName()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher("select Name from Win32_Processor"))
                {
                    foreach (ManagementObject obj in searcher.Get())
                    {
                        var name = obj["Name"];
                        return name == null ? null : name.ToString();
                    }
                }
            }
            catch { }
            return "Unknown CPU";
        }

        static string GetMemoryInfo()
        {
            try
            {
                using (var searcher = new ManagementObjectSearcher("select TotalVisibleMemorySize, FreePhysicalMemory from Win32_OperatingSystem"))
                {
                    foreach (ManagementObject obj in searcher.Get())
                    {
                        ulong totalKb = (ulong)obj["TotalVisibleMemorySize"];
                        ulong freeKb  = (ulong)obj["FreePhysicalMemory"];
                        return string.Format("Total: {0:F2} GB, Free: {1:F2} GB", totalKb / 1024.0 / 1024.0, freeKb / 1024.0 / 1024.0);
                    }
                }
            }
            catch { }
            return "Unknown Memory";
        }

        static string GetVirtualMachineInfo()
        {
            try
            {
                string[] vmKeywords = new[] { "vmware", "virtualbox", "virtual machine", "kvm", "qemu", "xen", "bochs", "hyper-v", "parallels" };
                string text = "";

                using (var cs = new ManagementObjectSearcher("select Manufacturer, Model from Win32_ComputerSystem"))
                {
                    foreach (ManagementObject o in cs.Get())
                    {
                        text += (o["Manufacturer"] + " " + o["Model"] + " ").ToLowerInvariant();
                    }
                }

                using (var bios = new ManagementObjectSearcher("select Manufacturer, SMBIOSBIOSVersion from Win32_BIOS"))
                {
                    foreach (ManagementObject o in bios.Get())
                    {
                        text += (o["Manufacturer"] + " " + o["SMBIOSBIOSVersion"] + " ").ToLowerInvariant();
                    }
                }

                using (var bb = new ManagementObjectSearcher("select Manufacturer, Product from Win32_BaseBoard"))
                {
                    foreach (ManagementObject o in bb.Get())
                    {
                        text += (o["Manufacturer"] + " " + o["Product"] + " ").ToLowerInvariant();
                    }
                }

                foreach (var k in vmKeywords)
                {
                    if (text.Contains(k))
                        return "True";
                }
                return "False";
            }
            catch
            {
                return "Unknown";
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
        public static void WriteSystemInfo() { }
#endif
    }
}