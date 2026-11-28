package io.github.harisonbd.labelcheck;

import android.content.ClipData;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.util.Base64;
import android.webkit.JavascriptInterface;
import androidx.core.content.FileProvider;
import com.getcapacitor.BridgeActivity;
import java.io.File;
import java.io.FileOutputStream;

// v2.45: the Label Check app. The page is the website (capacitor.config.json, server.url). This class only adds
// "LCNative": a file or a text goes to the Android share menu, because an Android WebView cannot download files
// and has no Web Share. The page uses it for "Export backup", the "To check" file for Claude, and "Share".
public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new Native(), "LCNative");
    }

    public class Native {
        @JavascriptInterface
        public boolean shareFile(String name, String mime, String base64, String text) {
            try {
                File dir = new File(getCacheDir(), "share");
                if (!dir.exists() && !dir.mkdirs()) return false;
                File[] old = dir.listFiles();
                if (old != null) for (File f : old) f.delete();
                String safe = (name == null || name.isEmpty()) ? "file" : name.replaceAll("[^A-Za-z0-9._-]", "_");
                File file = new File(dir, safe);
                try (FileOutputStream out = new FileOutputStream(file)) {
                    out.write(Base64.decode(base64, Base64.DEFAULT));
                }
                Uri uri = FileProvider.getUriForFile(MainActivity.this, getPackageName() + ".fileprovider", file);
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType(mime == null || mime.isEmpty() ? "application/octet-stream" : mime);
                send.putExtra(Intent.EXTRA_STREAM, uri);
                if (text != null && !text.isEmpty()) send.putExtra(Intent.EXTRA_TEXT, text);
                send.setClipData(ClipData.newRawUri(safe, uri));
                send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                Intent chooser = Intent.createChooser(send, safe);
                runOnUiThread(() -> startActivity(chooser));
                return true;
            } catch (Exception e) {
                return false;
            }
        }

        @JavascriptInterface
        public boolean shareText(String text) {
            try {
                Intent send = new Intent(Intent.ACTION_SEND);
                send.setType("text/plain");
                send.putExtra(Intent.EXTRA_TEXT, text == null ? "" : text);
                Intent chooser = Intent.createChooser(send, "Label Check");
                runOnUiThread(() -> startActivity(chooser));
                return true;
            } catch (Exception e) {
                return false;
            }
        }
    }
}
