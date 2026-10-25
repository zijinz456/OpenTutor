using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.IO.Compression;
using System.Linq;
using System.Security.Cryptography;
using System.Text;
using System.Threading.Tasks;
using System.Windows.Forms;

[assembly:System.Reflection.AssemblyTitle("OpenTutor Windows 安装程序")]
[assembly:System.Reflection.AssemblyVersion("1.2.0.0")]

internal static class SetupProgram {
    [STAThread] static int Main(string[] args) {
        AppContext.SetSwitch("Switch.System.IO.UseLegacyPathHandling",false);AppContext.SetSwitch("Switch.System.IO.BlockLongPaths",false);
        Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
        if(!Environment.Is64BitOperatingSystem){MessageBox.Show("本安装包需要 Windows 10/11 64 位。","OpenTutor");return 1;}
        try {
            if(args.Length==2&&args[0]=="--extract") {Package.Install(args[1],false,null);return 0;}
            if(args.Length==2&&args[0]=="--self-test") {
                using(var form=new SetupWindow()) {
                    form.StartPosition=FormStartPosition.Manual;form.Location=new Point(-32000,-32000);
                    form.Show();form.PerformLayout();Application.DoEvents();
                    using(var bitmap=new Bitmap(form.Width,form.Height)){form.DrawToBitmap(bitmap,new Rectangle(Point.Empty,bitmap.Size));bitmap.Save(args[1]);}
                    form.Close();
                }return 0;
            }
            Application.Run(new SetupWindow());return 0;
        }catch(Exception error){Console.Error.WriteLine(error.Message);if(args.Length==0)MessageBox.Show(error.Message,"安装未完成");return 1;}
    }
}

internal sealed class SetupWindow:Form {
    readonly TextBox location=new TextBox();readonly Label status=new Label();readonly ProgressBar progress=new ProgressBar();
    readonly Button install=new Button();readonly Button browse=new Button();readonly CheckBox shortcuts=new CheckBox();
    bool installing,complete;
    public SetupWindow(){
        Text="OpenTutor · 安装";ClientSize=new Size(620,460);FormBorderStyle=FormBorderStyle.FixedDialog;MaximizeBox=false;
        StartPosition=FormStartPosition.CenterScreen;Font=new Font("Microsoft YaHei UI",10);BackColor=Color.FromArgb(245,248,246);
        Icon=Icon.ExtractAssociatedIcon(Application.ExecutablePath);
        var title=new Label{Text="把资料变成你的学习课堂",Font=new Font(Font.FontFamily,21,FontStyle.Bold),AutoSize=true,Location=new Point(28,26)};
        var detail=new Label{Text="内置运行环境，无需 Docker、Python 或 Node.js。\n首次打开后，在设置中填写自己的模型与 API。",Location=new Point(30,82),Size=new Size(556,56)};
        var label=new Label{Text="安装位置（请选择可写的空目录）",AutoSize=true,Location=new Point(30,158)};
        location.Text=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),"OpenTutor");
        location.Location=new Point(30,187);location.Size=new Size(454,30);
        browse.Text="浏览…";browse.Location=new Point(494,184);browse.Size=new Size(94,34);
        browse.Click+=(s,e)=>{using(var dialog=new FolderBrowserDialog()){dialog.Description="选择一个空文件夹安装 OpenTutor";if(dialog.ShowDialog()==DialogResult.OK)location.Text=dialog.SelectedPath;}};
        shortcuts.Text="创建桌面和开始菜单快捷方式";shortcuts.Checked=true;shortcuts.AutoSize=true;shortcuts.Location=new Point(30,235);
        var note=new Label{Text="学习数据只保存在安装目录中；请保留 native-data 文件夹。\n安装过程不需要联网；调用在线模型时需要网络和你自己的 API。",Location=new Point(30,274),Size=new Size(558,54),ForeColor=Color.DimGray};
        status.Text="准备安装 · Windows 10/11 64 位";status.Location=new Point(30,336);status.Size=new Size(556,34);
        progress.Location=new Point(30,377);progress.Size=new Size(556,12);
        install.Text="安装";install.Location=new Point(436,407);install.Size=new Size(150,34);
        install.Click+=async(s,e)=>{
            if(complete){Process.Start(new ProcessStartInfo(Path.Combine(location.Text,"OpenTutor.exe")){UseShellExecute=true});Close();return;}
            if(installing)return;
            installing=true;install.Enabled=false;browse.Enabled=false;location.ReadOnly=true;shortcuts.Enabled=false;
            try {
                var destination=location.Text;var links=shortcuts.Checked;
                var report=new Progress<int>(value=>{progress.Value=value;status.Text=value<20?"正在检查安装包…":"正在安装，请稍候…";});
                await Task.Run(()=>Package.Install(destination,links,report));
                complete=true;progress.Value=100;status.Text="安装完成，点击“打开学习”配置自己的 API。";install.Text="打开学习";
            }catch(Exception error){status.Text="安装未完成";MessageBox.Show(error.Message,"OpenTutor");location.ReadOnly=false;browse.Enabled=true;shortcuts.Enabled=true;}
            finally{installing=false;install.Enabled=true;}
        };
        FormClosing+=(s,e)=>{if(installing)e.Cancel=true;};
        Controls.AddRange(new Control[]{title,detail,label,location,browse,shortcuts,note,status,progress,install});
    }
}

internal static class Package {
    const string Magic="OpenTutorPkgV1!!";
    public static void Install(string directory,bool shortcuts,IProgress<int> progress){
        string root=Path.GetFullPath(directory.Trim());
        if(root.StartsWith(@"\\")||root.Length<4)throw new IOException("请选择本机磁盘中的可写空目录。");
        if(Directory.Exists(root)&&Directory.EnumerateFileSystemEntries(root).Any())throw new IOException("目标目录不是空目录。请另选空目录；已有学习文件不会被覆盖。");
        string parent=Path.GetDirectoryName(root);Directory.CreateDirectory(parent);
        if((File.GetAttributes(parent)&FileAttributes.ReparsePoint)!=0)throw new IOException("请选择普通文件夹，不要使用目录链接。");
        using(var file=File.OpenRead(Application.ExecutablePath)){
            if(file.Length<56)throw new IOException("安装包不完整，请重新获取。");
            file.Position=file.Length-56;
            using(var reader=new BinaryReader(file,Encoding.UTF8,true)){
                long size=reader.ReadInt64();byte[] expected=reader.ReadBytes(32);string magic=Encoding.ASCII.GetString(reader.ReadBytes(16));
                long start=file.Length-56-size;
                if(magic!=Magic||size<=0||start<0)throw new IOException("安装包不完整，请重新获取。");
                using(var payload=new PayloadStream(file,start,size)){
                    using(var sha=SHA256.Create())if(!sha.ComputeHash(payload).SequenceEqual(expected))throw new IOException("安装包校验失败，请重新获取。");
                    if(progress!=null)progress.Report(20);payload.Position=0;
                    using(var archive=new ZipArchive(payload,ZipArchiveMode.Read,true)){
                        var paths=new System.Collections.Generic.HashSet<string>(StringComparer.OrdinalIgnoreCase);
                        foreach(var entry in archive.Entries){
                            string name=entry.FullName.Replace('/',Path.DirectorySeparatorChar);
                            string target=Path.GetFullPath(Path.Combine(root,name));
                            if(!target.StartsWith(root+Path.DirectorySeparatorChar,StringComparison.OrdinalIgnoreCase)||name.Contains(":")||!paths.Add(target))throw new IOException("安装包包含无效路径。");
                            if(((entry.ExternalAttributes>>16)&0xF000)==0xA000)throw new IOException("安装包包含目录链接。");
                        }
                        long bytes=archive.Entries.Sum(e=>e.Length);
                        if(new DriveInfo(Path.GetPathRoot(root)).AvailableFreeSpace<bytes+268435456)throw new IOException("磁盘空间不足，请至少预留 "+((bytes+268435456)/1048576)+" MB。");
                        Directory.CreateDirectory(root);int index=0;
                        foreach(var entry in archive.Entries){
                            string target=Path.GetFullPath(Path.Combine(root,entry.FullName.Replace('/',Path.DirectorySeparatorChar)));
                            Directory.CreateDirectory(Path.GetDirectoryName(target));
                            using(var input=entry.Open())using(var output=new FileStream(target,FileMode.CreateNew,FileAccess.Write))input.CopyTo(output);
                            if(progress!=null)progress.Report(20+(++index*75/archive.Entries.Count));
                        }
                    }
                }
            }
        }
        var init=new ProcessStartInfo {
            FileName=Path.Combine(root,@".runtime\python\python.exe"),
            Arguments="-I -X utf8 \""+Path.Combine(root,@"scripts\native-init.py")+"\"",
            WorkingDirectory=root,UseShellExecute=false,CreateNoWindow=true,WindowStyle=ProcessWindowStyle.Hidden,
            RedirectStandardOutput=true,RedirectStandardError=true
        };
        using(var process=Process.Start(init)){
            string output=process.StandardOutput.ReadToEnd();string errors=process.StandardError.ReadToEnd();
            if(!process.WaitForExit(30000)||process.ExitCode!=0)throw new IOException("文件已解压，但初始化未完成："+errors+output);
        }
        if(shortcuts){
            MakeLink(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.DesktopDirectory),"OpenTutor 本地学习.lnk"),root);
            string menu=Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Programs),"OpenTutor");Directory.CreateDirectory(menu);
            MakeLink(Path.Combine(menu,"OpenTutor 本地学习.lnk"),root);
        }
        if(progress!=null)progress.Report(100);
    }
    static void MakeLink(string name,string root){
        var type=Type.GetTypeFromProgID("WScript.Shell");object shell=Activator.CreateInstance(type);
        object link=type.InvokeMember("CreateShortcut",System.Reflection.BindingFlags.InvokeMethod,null,shell,new object[]{name});
        var lt=link.GetType();var flags=System.Reflection.BindingFlags.SetProperty;
        lt.InvokeMember("TargetPath",flags,null,link,new object[]{Path.Combine(root,"OpenTutor.exe")});
        lt.InvokeMember("WorkingDirectory",flags,null,link,new object[]{root});
        lt.InvokeMember("Description",flags,null,link,new object[]{"OpenTutor 本地 AI 学习"});
        lt.InvokeMember("IconLocation",flags,null,link,new object[]{Path.Combine(root,"OpenTutor.exe")+",0"});
        lt.InvokeMember("Save",System.Reflection.BindingFlags.InvokeMethod,null,link,null);
        System.Runtime.InteropServices.Marshal.FinalReleaseComObject(link);System.Runtime.InteropServices.Marshal.FinalReleaseComObject(shell);
    }
}

// ZipArchive must see offsets relative to the payload, rather than the EXE prefix.
internal sealed class PayloadStream:Stream {
    readonly Stream source;readonly long start,size;long position;
    public PayloadStream(Stream stream,long offset,long length){source=stream;start=offset;size=length;}
    public override bool CanRead{get{return true;}}public override bool CanSeek{get{return true;}}public override bool CanWrite{get{return false;}}
    public override long Length{get{return size;}}public override long Position{get{return position;}set{if(value<0||value>size)throw new IOException("Invalid package position");position=value;}}
    public override int Read(byte[] buffer,int offset,int count){source.Position=start+position;int read=source.Read(buffer,offset,(int)Math.Min(count,size-position));position+=read;return read;}
    public override long Seek(long offset,SeekOrigin origin){Position=origin==SeekOrigin.Begin?offset:origin==SeekOrigin.Current?position+offset:size+offset;return position;}
    public override void Flush(){}public override void SetLength(long value){throw new NotSupportedException();}public override void Write(byte[] buffer,int offset,int count){throw new NotSupportedException();}
}
