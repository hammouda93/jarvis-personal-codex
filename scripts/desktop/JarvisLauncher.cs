using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Windows.Forms;

[assembly: AssemblyTitle("Jarvis Personal")]
[assembly: AssemblyDescription("Lancement direct de Jarvis Personal")]
[assembly: AssemblyProduct("Jarvis Personal")]
[assembly: AssemblyVersion("1.0.0.0")]

internal static class JarvisLauncher
{
    [STAThread]
    private static int Main(string[] args)
    {
        bool check = args.Length == 1 && args[0] == "--check";
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string logPath = null;
        try
        {
            if (check)
            {
                // A winexe has no console code page to reconfigure. Encode the
                // redirected handles directly so accented paths stay intact.
                Console.SetOut(new StreamWriter(Console.OpenStandardOutput(), new UTF8Encoding(false)) { AutoFlush = true });
                Console.SetError(new StreamWriter(Console.OpenStandardError(), new UTF8Encoding(false)) { AutoFlush = true });
            }
            if (args.Length != 0 && !check)
                throw new ArgumentException("Lancez Jarvis sans argument, ou utilisez --check pour le diagnostic.");
            string python = Path.Combine(root, ".venv", "Scripts", "python.exe");
            string entry = Path.Combine(root, "run_jarvis.py");
            string script = check ? Path.Combine(root, "scripts", "check_desktop_startup.py") : entry;
            if (!File.Exists(python))
                throw new FileNotFoundException("L'environnement .venv de Jarvis est introuvable. Conservez Jarvis.exe dans le dossier du projet.");
            if (!File.Exists(entry) || !File.Exists(script))
                throw new FileNotFoundException("Les fichiers de Jarvis sont introuvables. Conservez Jarvis.exe dans le dossier du projet.");

            using (Mutex instance = new Mutex(false, MutexName(root)))
            {
                bool acquired = false;
                if (!check)
                {
                    try { acquired = instance.WaitOne(0); }
                    catch (AbandonedMutexException) { acquired = true; }
                    if (!acquired)
                    {
                        MessageBox.Show("Jarvis est déjà ouvert pour ce projet.", "Jarvis Personal",
                            MessageBoxButtons.OK, MessageBoxIcon.Information);
                        return 0;
                    }
                }
                try
                {
                    string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
                    if (String.IsNullOrWhiteSpace(local))
                        local = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
                    string logs = Path.Combine(local, "JarvisPersonal", "logs");
                    Directory.CreateDirectory(logs);
                    logPath = Path.Combine(logs, "desktop_" + DateTime.Now.ToString("yyyyMMdd_HHmmss")
                        + "_" + Process.GetCurrentProcess().Id + ".log");
                    using (StreamWriter log = new StreamWriter(logPath, false, new UTF8Encoding(false)))
                    using (Process child = new Process())
                    {
                        log.AutoFlush = true;
                        log.WriteLine("[DESKTOP] root=" + root + " check=" + check);
                        object gate = new object();
                        child.StartInfo = new ProcessStartInfo(python, "-u \"" + script + "\"")
                        {
                            WorkingDirectory = root,
                            UseShellExecute = false,
                            CreateNoWindow = true,
                            RedirectStandardOutput = true,
                            RedirectStandardError = true,
                            StandardOutputEncoding = Encoding.UTF8,
                            StandardErrorEncoding = Encoding.UTF8
                        };
                        child.StartInfo.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
                        child.StartInfo.EnvironmentVariables["PYTHONUTF8"] = "1";
                        child.StartInfo.EnvironmentVariables["VIRTUAL_ENV"] = Path.Combine(root, ".venv");
                        child.StartInfo.EnvironmentVariables["PATH"] = Path.Combine(root, ".venv", "Scripts")
                            + Path.PathSeparator + (child.StartInfo.EnvironmentVariables["PATH"] ?? "");
                        child.StartInfo.EnvironmentVariables.Remove("PYTHONHOME");
                        if (check)
                            child.StartInfo.EnvironmentVariables["QT_QPA_PLATFORM"] = "offscreen";
                        child.OutputDataReceived += delegate(object sender, DataReceivedEventArgs e)
                        {
                            if (e.Data == null) return;
                            lock (gate)
                            {
                                try { log.WriteLine(e.Data); } catch (IOException) { }
                                if (check) Console.WriteLine(e.Data);
                            }
                        };
                        child.ErrorDataReceived += delegate(object sender, DataReceivedEventArgs e)
                        {
                            if (e.Data == null) return;
                            lock (gate)
                            {
                                try { log.WriteLine(e.Data); } catch (IOException) { }
                                if (check) Console.Error.WriteLine(e.Data);
                            }
                        };
                        child.Start();
                        child.BeginOutputReadLine();
                        child.BeginErrorReadLine();
                        if (check && !child.WaitForExit(30000))
                        {
                            child.Kill();
                            child.WaitForExit();
                            throw new TimeoutException("Le diagnostic de démarrage a dépassé 30 secondes.");
                        }
                        // Also drain both asynchronous streams before closing the log.
                        child.WaitForExit();
                        log.WriteLine("[DESKTOP] exit=" + child.ExitCode);
                        if (!check && child.ExitCode != 0)
                            MessageBox.Show("Jarvis s'est arrêté avec une erreur.\n\nJournal : " + logPath,
                                "Jarvis Personal", MessageBoxButtons.OK, MessageBoxIcon.Error);
                        return child.ExitCode;
                    }
                }
                finally { if (acquired) instance.ReleaseMutex(); }
            }
        }
        catch (Exception error)
        {
            string message = "Impossible de démarrer Jarvis.\n\n" + error.Message;
            if (logPath != null) message += "\n\nJournal : " + logPath;
            if (check) Console.Error.WriteLine(message);
            else MessageBox.Show(message, "Jarvis Personal", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }

    private static string MutexName(string root)
    {
        using (SHA256 hash = SHA256.Create())
        {
            byte[] bytes = hash.ComputeHash(Encoding.UTF8.GetBytes(Path.GetFullPath(root).ToUpperInvariant()));
            return "Local\\JarvisPersonal_" + BitConverter.ToString(bytes, 0, 12).Replace("-", "");
        }
    }
}
