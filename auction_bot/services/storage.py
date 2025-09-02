from __future__ import annotations
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Optional
from aiogram.types import Document

from ..config import settings

class FileStorage:
    """Сервис для хранения файлов тендеров"""
    
    def __init__(self):
        self.files_dir = Path(settings.FILES_DIR)
        self.files_dir.mkdir(exist_ok=True)
    
    async def save_tender_file(self, document: Document, user_id: int, tender_title: str) -> str:
        """Сохранение файла тендера"""
        try:
            # Создаем безопасное имя файла
            safe_title = "".join(c for c in tender_title if c.isalnum() or c in (' ', '-', '_')).rstrip()
            safe_title = safe_title.replace(' ', '_')
            
            # Формируем имя файла
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            file_extension = Path(document.file_name).suffix if document.file_name else '.pdf'
            filename = f"tender_{user_id}_{safe_title}_{timestamp}{file_extension}"
            
            # Полный путь к файлу
            file_path = self.files_dir / filename
            
            # Скачиваем файл
            await document.bot.download(document, str(file_path))
            
            return str(file_path)
            
        except Exception as e:
            print(f"Ошибка сохранения файла: {e}")
            return None
    
    def get_file_path(self, filename: str) -> Optional[Path]:
        """Получение пути к файлу"""
        file_path = self.files_dir / filename
        if file_path.exists():
            return file_path
        return None
    
    def delete_file(self, filename: str) -> bool:
        """Удаление файла"""
        try:
            file_path = self.files_dir / filename
            if file_path.exists():
                file_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Ошибка удаления файла: {e}")
            return False
    
    def list_tender_files(self, user_id: int) -> list:
        """Список файлов пользователя"""
        try:
            files = []
            for file_path in self.files_dir.iterdir():
                if file_path.is_file() and file_path.name.startswith(f"tender_{user_id}_"):
                    files.append({
                        'name': file_path.name,
                        'size': file_path.stat().st_size,
                        'created': datetime.fromtimestamp(file_path.stat().st_ctime)
                    })
            return sorted(files, key=lambda x: x['created'], reverse=True)
        except Exception as e:
            print(f"Ошибка получения списка файлов: {e}")
            return []
    
    def cleanup_old_files(self, days: int = 30) -> int:
        """Очистка старых файлов"""
        try:
            cutoff_date = datetime.now().timestamp() - (days * 24 * 60 * 60)
            deleted_count = 0
            
            for file_path in self.files_dir.iterdir():
                if file_path.is_file():
                    if file_path.stat().st_ctime < cutoff_date:
                        try:
                            file_path.unlink()
                            deleted_count += 1
                        except Exception as e:
                            print(f"Ошибка удаления старого файла {file_path}: {e}")
            
            return deleted_count
        except Exception as e:
            print(f"Ошибка очистки старых файлов: {e}")
            return 0
    
    def get_storage_info(self) -> dict:
        """Информация о хранилище"""
        try:
            total_size = 0
            file_count = 0
            
            for file_path in self.files_dir.iterdir():
                if file_path.is_file():
                    total_size += file_path.stat().st_size
                    file_count += 1
            
            return {
                'total_files': file_count,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'storage_path': str(self.files_dir.absolute())
            }
        except Exception as e:
            print(f"Ошибка получения информации о хранилище: {e}")
            return {}
    
    def validate_file_type(self, document: Document) -> bool:
        """Проверка типа файла"""
        allowed_extensions = ['.pdf', '.doc', '.docx', '.txt', '.rtf']
        
        if document.file_name:
            file_ext = Path(document.file_name).suffix.lower()
            return file_ext in allowed_extensions
        
        return False
    
    def get_file_size_mb(self, document: Document) -> float:
        """Получение размера файла в МБ"""
        if document.file_size:
            return round(document.file_size / (1024 * 1024), 2)
        return 0.0
    
    def check_file_size_limit(self, document: Document, max_size_mb: float = 10.0) -> bool:
        """Проверка лимита размера файла"""
        file_size_mb = self.get_file_size_mb(document)
        return file_size_mb <= max_size_mb