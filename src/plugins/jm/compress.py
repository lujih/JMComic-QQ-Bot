import os

from PIL import Image

from jmcomic import Feature, jm_log


def compress_image_in_place(filepath: str, quality: int, convert_to_jpeg: bool = False):
    """JPEG/WEBP 原地重压缩（移植自上游 usage/workflow_download.py e3c7e40）。

    PNG 与多帧 GIF 不支持压缩，原样返回。
    返回: (格式, 原大小, 压缩后大小, 是否替换, 最终路径, 跳过原因)
    """
    target_path = filepath
    temp_path = f'{filepath}.jmcomic-compress.tmp'
    original_size = os.path.getsize(filepath)

    try:
        with Image.open(filepath) as image:
            image_format = image.format
            image_info = image.info.copy()
            save_kwargs = {}

            if getattr(image, 'n_frames', 1) > 1:
                return image_format, None, None, False, filepath, 'multi_frame'

            if convert_to_jpeg and image_format in {'PNG', 'WEBP'}:
                image_format = 'JPEG'
                target_path = os.path.splitext(filepath)[0] + '.jpg'
                if image.mode not in {'RGB', 'L'}:
                    if image.mode in {'RGBA', 'LA'} or 'transparency' in image_info:
                        image = image.convert('RGBA')
                        background = Image.new('RGB', image.size, 'white')
                        background.paste(image, mask=image.getchannel('A'))
                        image = background
                    else:
                        image = image.convert('RGB')
                save_kwargs.update(quality=quality, optimize=True)
            elif image_format in {'JPEG', 'JPG'}:
                save_kwargs.update(quality=quality, optimize=True)
            elif image_format == 'WEBP':
                save_kwargs.update(quality=quality)
            elif image_format == 'PNG':
                return image_format, None, None, False, filepath, 'unsupported_format'
            else:
                return image_format, None, None, False, filepath, 'unsupported_format'

            for key in ('exif', 'icc_profile'):
                value = image_info.get(key)
                if value is not None:
                    save_kwargs[key] = value

            image.save(temp_path, format=image_format, **save_kwargs)

        compressed_size = os.path.getsize(temp_path)
        if target_path == filepath and compressed_size >= original_size:
            os.remove(temp_path)
            return image_format, original_size, compressed_size, False, filepath, None

        os.replace(temp_path, target_path)
        if target_path != filepath:
            os.remove(filepath)

        return image_format, original_size, compressed_size, True, target_path, None
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _files_of_dir(d: str) -> list[str]:
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, f) for f in os.listdir(d) if os.path.isfile(os.path.join(d, f))]


# 自适应压缩档位：从 60 起尝试，未减小则降档。
# 实测：源图解码质量较高（q75 仅 -2%），q60 约 -13%、q50 约 -24%；JPEG 对 zip 二次压缩收益 ≈ 图片压缩收益
_COMPRESS_QUALITIES = (60, 50)


class CompressZipFeature(Feature):
    """zip 导出前压缩源图。

    挂在 after_album：经 FeatureChain 组合时须位于 export_zip 之前
    （_invoke_features_for 按注册顺序执行，压缩先于打包）。
    禁漫图片解码后为 JPEG；按 (60, 50) 逐档尝试，均未减小则保留原图。
    """

    def should_invoke(self, feature_from: str, when: str) -> bool:
        return feature_from == 'download_album' and when == 'after_album'

    def invoke(self, option, feature_from: str, when: str, **kwargs):
        album = kwargs.get('album')
        if album is None:
            return

        compressed = skipped = kept = 0
        for photo in album:
            img_dir = option.decide_image_save_dir(photo)
            for img_path in _files_of_dir(img_dir):
                for quality in _COMPRESS_QUALITIES:
                    fmt, orig, final, replaced, _, _ = compress_image_in_place(img_path, quality)
                    if orig is None or fmt == 'PNG':
                        skipped += 1
                        break
                    if replaced:
                        compressed += 1
                        break
                else:
                    kept += 1

        jm_log('jm.compress',
               f'zip 源图压缩完成: 压缩 {compressed} 张, 跳过 {skipped} 张, 保持原图 {kept} 张'
               f' (档位 {_COMPRESS_QUALITIES})')
