using System.Runtime.InteropServices;
using System.Text;
using System.Windows;
using Microsoft.Win32;

namespace RadioBrowserSmtcHost;

public partial class App : Application
{
    private const string AppUserModelId = "RadioBrowser.SMTC.Host";
    private const int AppModelErrorNoPackage = 15700;

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(
        string appID
    );

    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern int GetCurrentPackageFullName(ref int packageFullNameLength, StringBuilder? packageFullName);

    protected override void OnStartup(StartupEventArgs e)
    {
        ConfigureAppIdentity();
        base.OnStartup(e);
    }

    private static void ConfigureAppIdentity()
    {
        if (IsPackagedProcess())
        {
            return;
        }

        try
        {
            SetCurrentProcessExplicitAppUserModelID(AppUserModelId);

            using var key = Registry.CurrentUser.CreateSubKey(
                $@"Software\Classes\AppUserModelId\{AppUserModelId}"
            );
            if (key is null)
            {
                return;
            }

            key.SetValue("DisplayName", "Radio Browser", RegistryValueKind.String);
            key.SetValue("InfoTip", "Media bridge for Radio Browser MCP", RegistryValueKind.String);
        }
        catch
        {
            // Non-fatal: media playback must still work even if identity registration fails.
        }
    }

    private static bool IsPackagedProcess()
    {
        var length = 0;
        var result = GetCurrentPackageFullName(ref length, null);
        return result != AppModelErrorNoPackage;
    }
}
