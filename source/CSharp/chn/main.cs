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
        DebugLog.Init("main.exe 开始运行");
        DebugLog.WriteSystemInfo();
        DebugLog.Write("参数: " + string.Join(" ", args));

        if (IsReactOS())
        {
            WriteRed("==================================================================");
            WriteRed("[!] 检测到当前系统为 ReactOS");
            WriteRed("[!] 本工具不支持在 ReactOS 环境下运行");
            WriteRed("[!] ReactOS 尚未达到与 Windows 完全兼容的程度");
            WriteRed("[!] 请使用真实 Windows 或 Wine + Linux 环境");
            WriteRed("==================================================================");
            Console.WriteLine();
            Console.Write("请按回车键退出...");
            Console.ReadLine();
            Environment.Exit(1);
        }

        if (IsRunningInWine())
        {
            WriteYellow("========================================================================");
            WriteYellow("[!] 检测到运行在 Wine 容器中");
            WriteYellow("[*] 盘符可以在以下位置查看: ~/.wine/dosdevices/");
            WriteYellow("[*] 或查看: /home/[用户名]/.wine/dosdevices/");
            WriteYellow("========================================================================");
            Console.WriteLine();
        }
        
        Console.Title = "vivo 4系内核 全自动修补工具 请输入boot.img路径";

#if DEBUG
        WriteRed("WARNING: 这是Debug构建。debug.log将被写入用户桌面。");
#endif

        WriteCyan("============================================================================");
        WriteCyan("                 vivo 4系内核 全自动修补工具");
        WriteCyan("                工具作者:MyAngelAnchorage");
        WriteCyan("        仓库:https://github.com/4accccc/vivo-4.x-kernel-autopatch");
        WriteCyan("                       方案作者:romanovj");
        WriteCyan("============================================================================");

        string MagiskBoot = @".\magiskboot.exe";
        string PatchEXE = @".\patch.exe";

        if (!File.Exists(MagiskBoot))
            Fatal("[!] 未找到 magiskboot.exe，终止。");

        if (!File.Exists(PatchEXE))
            Fatal("[!] 未找到 patch.exe，终止。");

        Console.Write("[*] 请输入 boot.img 文件的完整路径（例如 D:\\boot.img），路径最好不加引号：");
        string BootImg = Console.ReadLine().Trim('"');

        if (string.IsNullOrWhiteSpace(BootImg))
            Fatal("[!] 未输入 boot.img，终止。");

        if (!File.Exists(BootImg))
            Fatal("[!] boot.img 文件不存在，终止。");

        if ((File.GetAttributes(BootImg) & FileAttributes.Directory) != 0)
            Fatal("[!] 输入的是文件夹而非文件，终止。");

        WriteGreen(string.Format("[*] 已确认 boot.img: {0}", BootImg));

        Console.Title = "vivo 4系内核 全自动修补工具 请输入修补后boot.img保存路径";

        Console.Write("[*] 请输入保存修补后boot文件的完整路径（留空则保存到boot.img同目录），路径最好不加引号：");
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
                    WriteYellow("[!] 指定的是已存在的文件，将覆盖该文件。");
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
                WriteYellow("[!] 指定路径不可写，默认保存到 boot.img 所在目录。");
                FinalOutputPath = FallbackPath;
            }
        }
        else
        {
            WriteYellow("[*] 未指定保存路径，默认保存到 boot.img 所在目录。");
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
            Fatal("[!] 默认路径不可写！请检查文件夹权限！");
        }

        DebugLog.Write("BootImg 位置: " + BootImg);
        DebugLog.Write("UserSave 输入: " + UserSave);
        DebugLog.Write("输出位置: " + FinalOutputPath);

        Console.Title = "vivo 4系内核 全自动修补工具 正在解包boot.img";
        WriteYellow("[*] 开始解包 boot.img ...");
        Run(MagiskBoot, string.Format("unpack \"{0}\"", BootImg), "unpack_log.txt");

        Console.Title = "vivo 4系内核 全自动修补工具 正在查找 kernel 文件";

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
            Fatal("[!] 未找到 kernel（请检查 unpack_log.txt）。");

        if (KernelFile.EndsWith(".gz") || KernelFile.EndsWith(".lz4") || KernelFile.EndsWith(".lzma"))
        {
            WriteYellow(string.Format("[*] 发现压缩内核 {0}，正在解压...", KernelFile));
            Run(MagiskBoot, string.Format("decompress \"{0}\" kernel_decompressed", KernelFile), null);

            if (!File.Exists("kernel_decompressed"))
                Fatal("[!] 解压失败。");

            KernelFile = "kernel_decompressed";
        }

        WriteGreen("[+] 内核文件路径: " + KernelFile);
        string kernelHashBefore = CalcSHA256(KernelFile);
        if (kernelHashBefore == null)
            WriteRed("[!] 无法计算修补前 kernel 的 SHA256！");

        DebugLog.Write("Kernel SHA256 (修补前): " + kernelHashBefore);
        WriteYellow("[*] 开始修补内核...");

        Run(PatchEXE, string.Format("\"{0}\" -calledByMain", KernelFile), null);
        string kernelHashAfter = CalcSHA256(KernelFile);
        if (kernelHashAfter == null)
            WriteRed("[!] 无法计算修补后 kernel 的 SHA256！，终止。");

        DebugLog.Write("Kernel SHA256 (修补后): " + kernelHashAfter);
        Console.Title = "vivo 4系内核 全自动修补工具 内核修补完成";

        string status = File.Exists("patch_status.log") ? File.ReadAllText("patch_status.log") : "Fail";

        if (status.Contains("没有找到对应地址"))
            FailStatus("[Failed] 内核修补失败，未找到对应地址，终止操作！");

        if (status.Contains("找不到 kernel 文件"))
            FailStatus("[Failed] 软件找不到 kernel 文件，终止操作！");

        if (status.Contains("你直接运行了patch"))
            FailStatus("[Failed] 参数传输异常，终止操作！");

        if (!status.Contains("SUCCESS"))
            FailStatus("[Failed] 由于未知原因内核修补未成功，终止操作！");

        Console.Title = "vivo 4系内核 全自动修补工具 正在重打包boot.img";
        WriteYellow("[*] 修补成功，继续重新打包 boot.img ...");
        Run(MagiskBoot, string.Format("repack \"{0}\"", BootImg), "repack_log.txt");

        if (!File.Exists("new-boot.img"))
            Fatal("[!] 重新打包 boot.img 失败！");

        Thread.Sleep(300);
        DebugLog.Write("复制 new-boot.img -> patched-boot.img");
        File.Copy("new-boot.img", "patched-boot.img", true);

        DebugLog.Write("复制 patched-boot.img -> " + FinalOutputPath);
        File.Copy("patched-boot.img", FinalOutputPath, true);

        Console.Title = "vivo 4系内核 全自动修补工具 自动修补完成";
        Console.WriteLine("==================================================================");
        WriteGreen("[SUCCESS]");
        WriteGreen("破解了su限制的boot.img已打包完成");
        WriteGreen("请自己将生成的boot.img放到面具里修补！");
        WriteGreen("输出路径: " + FinalOutputPath);
        WriteYellow("请注意：我们发现部分机型除了内核有限制以外，selinux也做了一定的限制，本工具不涉及修改selinux的范围。");
        Console.WriteLine("==================================================================");

        Console.Write("请按回车键退出...");
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
        DebugLog.Write("运行: " + exe);
        DebugLog.Write("参数: " + args);

        bool isPatch = Path.GetFileName(exe)
            .Equals("patch.exe", StringComparison.OrdinalIgnoreCase);

        var psi = new ProcessStartInfo(exe, args);

        if (isPatch)
        {
            DebugLog.Write("运行 patch.exe 附着于当前控制台");

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
        Console.Write("请按回车键退出...");
        Console.ReadLine();
        CleanupAndSelfDelete();
        Environment.Exit(1);
    }

    static void FailStatus(string msg)
    {
        Console.Title = "vivo 4系内核 全自动修补工具 修补失败";
        WriteRed("===============================================");
        WriteRed(msg);
        WriteRed("===============================================");
        Console.Write("请按回车键退出...");
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
                DebugLog.Write("检测到 ReactOS（OSVersion）: " + os);
                return true;
            }

            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"SOFTWARE\ReactOS"))
                {
                    if (key != null)
                    {
                        DebugLog.Write("检测到 ReactOS（注册表 HKLM\\SOFTWARE\\ReactOS）");
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
                    DebugLog.Write("通过环境变量检测到程序在wine容器内运行: " + envVar);
                    return true;
                }
            }

            try
            {
                using (var key = Microsoft.Win32.Registry.LocalMachine.OpenSubKey(@"Software\Wine"))
                {
                    if (key != null)
                    {
                        DebugLog.Write("通过注册表项检测到程序在wine容器内运行。");
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
                        DebugLog.Write("通过wine_get_version功能检测到程序在wine容器内运行。");
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
            DebugLog.Write("捕获 Ctrl+C / Ctrl+Break");

            CleanupAndSelfDelete();
            Environment.Exit(1);
        };

        SetConsoleCtrlHandler(ConsoleCtrlHandler, true);
    }

    static bool ConsoleCtrlHandler(CtrlTypes ctrlType)
    {
        if (_exiting) return false;
        _exiting = true;

        DebugLog.Write("捕获控制台关闭事件: " + ctrlType);

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
                        WriteYellow("WARNING: 这是Debug构建。debug.log将被写入C盘根目录。");
                        File.AppendAllText(LogFile, "\r\n========== " + title + " ==========\r\n");
                    }
                    catch
                    {
                        LogEnabled = false;
                        WriteRed("WARNING: 这是Debug构建。debug.log无法在用户桌面和系统盘根目录生成，请检查权限！");
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
                Write("系统: " + Environment.OSVersion.VersionString);
                Write("平台: " + Environment.OSVersion.Platform);
                Write("版本号: " + Environment.OSVersion.Version);
                Write("系统语言: " + CultureInfo.CurrentCulture.Name);
                Write("UI 语言: " + CultureInfo.CurrentUICulture.Name);
                Write("是否64位系统: " + Environment.Is64BitOperatingSystem);
                Write("是否为64位进程: " + Environment.Is64BitProcess);
                Write("CPU: " + GetCpuName());
                Write("内存: " + GetMemoryInfo());
                Write("是否为虚拟机: " + GetVirtualMachineInfo());
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
            return "未知 CPU";
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
                        return string.Format("Total: {0:F2} GB, Free: {1:F2} GB", totalKb / 1024.0 / 1024.0, freeKb  / 1024.0 / 1024.0);
                    }
                }
            }
            catch { }
            return "未知内存";
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
                return "未知";
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
            Write("异常: " + ex);
        }
#else
        public static void Init(string t) { }
        public static void Write(string m) { }
        public static void WriteException(Exception e) { }
        public static void WriteSystemInfo() { }
#endif
    }
}