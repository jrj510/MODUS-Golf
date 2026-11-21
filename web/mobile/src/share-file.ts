import { Capacitor } from '@capacitor/core';
import { Directory, Encoding, Filesystem } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
import { download } from '../../src/components';
export async function shareFile(filename: string, data: string, type: string) {
  if (!Capacitor.isNativePlatform()) {
    download(filename,data,type);
    return;
  }
  const {uri}=await Filesystem.writeFile({path:filename,data,directory:Directory.Cache,encoding:Encoding.UTF8});
  try {
    await Share.share({title:filename,files:[uri]});
  } finally {
    await Filesystem.deleteFile({path:filename,directory:Directory.Cache}).catch(() => {});
  }
}

