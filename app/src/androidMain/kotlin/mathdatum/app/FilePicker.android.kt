package mathdatum.app

import android.net.Uri
import android.provider.OpenableColumns
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext

@Composable
actual fun rememberTextFilePicker(onPicked: (name: String, text: String) -> Unit): () -> Unit {
    val context = LocalContext.current
    val current by rememberUpdatedState(onPicked)
    val launcher = rememberLauncherForActivityResult(ActivityResultContracts.OpenDocument()) { uri: Uri? ->
        if (uri != null) {
            val name = context.contentResolver.query(uri, null, null, null, null)?.use { c ->
                val i = c.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (i >= 0 && c.moveToFirst()) c.getString(i) else null
            } ?: (uri.lastPathSegment ?: "file")
            val text = context.contentResolver.openInputStream(uri)?.use { it.readBytes().decodeToString() }
            if (text != null) current(name, text)
        }
    }
    return remember(launcher) { { launcher.launch(arrayOf("*/*")) } }
}
