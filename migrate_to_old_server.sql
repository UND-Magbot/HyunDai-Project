-- ============================================================
-- 1차 서버 DB 마이그레이션 스크립트
-- 현재 DB 기준으로 추가된 테이블 및 컬럼을 1차 서버에 적용
-- 실행: mysql -u root -p1234 -h [1차서버IP] rcs_db < migrate_to_old_server.sql
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- 1. robots 테이블 컬럼 추가 (wcs_no)
-- ============================================================
ALTER TABLE `robots`
  ADD COLUMN IF NOT EXISTS `wcs_no` int(11) DEFAULT NULL;


-- ============================================================
-- 2. 신규 테이블: activity_logs
-- ============================================================
CREATE TABLE IF NOT EXISTS `activity_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `category` varchar(20) NOT NULL,
  `action` varchar(50) NOT NULL,
  `message` varchar(500) NOT NULL,
  `detail` mediumtext DEFAULT NULL,
  `robot_id` int(11) DEFAULT NULL,
  `robot_name` varchar(100) DEFAULT NULL,
  `source` varchar(100) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `ix_activity_logs_action` (`action`),
  KEY `ix_activity_logs_category` (`category`),
  KEY `ix_activity_logs_robot_id` (`robot_id`),
  KEY `idx_activity_logs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 3. 신규 테이블: system_logs
-- ============================================================
CREATE TABLE IF NOT EXISTS `system_logs` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `category` varchar(20) NOT NULL DEFAULT 'system',
  `action` varchar(50) NOT NULL DEFAULT '',
  `message` text NOT NULL,
  `detail` mediumtext DEFAULT NULL,
  `robot_id` int(11) DEFAULT NULL,
  `robot_name` varchar(100) DEFAULT NULL,
  `source` varchar(100) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  KEY `ix_system_logs_category` (`category`),
  KEY `ix_system_logs_action` (`action`),
  KEY `ix_system_logs_robot_id` (`robot_id`),
  KEY `idx_system_logs_created_at` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 4. 신규 테이블: menus
-- ============================================================
CREATE TABLE IF NOT EXISTS `menus` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `parent_id` int(11) DEFAULT NULL,
  `menu_key` varchar(50) NOT NULL,
  `menu_name` varchar(100) NOT NULL,
  `sort_order` int(11) NOT NULL,
  `is_active` tinyint(1) NOT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `menu_key` (`menu_key`),
  KEY `parent_id` (`parent_id`),
  CONSTRAINT `menus_ibfk_1` FOREIGN KEY (`parent_id`) REFERENCES `menus` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================
-- 5. 신규 테이블: user_permissions (menus 테이블 먼저 생성 필요)
-- ============================================================
CREATE TABLE IF NOT EXISTS `user_permissions` (
  `id` int(11) NOT NULL AUTO_INCREMENT,
  `user_id` int(11) NOT NULL,
  `menu_id` int(11) NOT NULL,
  `granted_by` int(11) DEFAULT NULL,
  `created_at` datetime NOT NULL DEFAULT current_timestamp(),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_user_menu` (`user_id`,`menu_id`),
  KEY `menu_id` (`menu_id`),
  KEY `granted_by` (`granted_by`),
  CONSTRAINT `user_permissions_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_permissions_ibfk_2` FOREIGN KEY (`menu_id`) REFERENCES `menus` (`id`) ON DELETE CASCADE,
  CONSTRAINT `user_permissions_ibfk_3` FOREIGN KEY (`granted_by`) REFERENCES `users` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- 완료
-- ============================================================
