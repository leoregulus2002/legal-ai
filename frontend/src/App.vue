<script setup lang="ts">
import { NConfigProvider, NGlobalStyle, NMessageProvider, zhCN, dateZhCN } from 'naive-ui'
import type { GlobalThemeOverrides } from 'naive-ui'

const theme: GlobalThemeOverrides = {
  common: {
    primaryColor: '#233d50',
    primaryColorHover: '#345469',
    primaryColorPressed: '#172938',
    infoColor: '#9a794a',
    successColor: '#376d51',
    bodyColor: '#f5f3ee',
    cardColor: '#fffefa',
    textColorBase: '#172938',
    borderColor: '#e5e0d6',
    borderRadius: '6px',
    fontFamily:
      '"Helvetica Neue", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
  },
}
</script>

<template>
  <NConfigProvider :locale="zhCN" :date-locale="dateZhCN" :theme-overrides="theme">
    <NGlobalStyle />
    <NMessageProvider>
      <RouterView />
    </NMessageProvider>
  </NConfigProvider>
</template>
