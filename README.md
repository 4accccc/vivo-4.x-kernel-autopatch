# vivo-4.x-kernel-autopatch


*tool was encrypted ← means u can not use it atm haha.*  
*will release soon*  
*really*  


<img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/autopatch-eng.png" width="27%" alt="example screenshot"><img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/autopatch-chn.png" width="25%" alt="示例截图">
<img src="https://raw.githubusercontent.com/4accccc/vivo-4x-kernel-patch/refs/heads/main/after_patch.png" width="50%" alt="效果图">


[releases](https://github.com/4accccc/vivo-4x-kernel-patch/releases).


### ⚠️WARNING: modifying a device's kernel can easily lead to a permanent "brick". if u r aware of that, or think my tool has some viruses™ inside, dont use this tool.


❓:need more feedback.      ✔️:tested OK.      ❌:smth went wrong.


|                  | 4.14.94+ | 4.14.98 | 4.14.141+ | 4.14.186 | 4.14.190 | 4.19.191+ |
| :--------------: | :------: | :-----: | :-------: | :------: | :------: | :-------: |
| **Status** |    ❓    |   ❓   |   ✔️   |   ❌¹   |   ❌¹   |   ❌¹   |


1:mount fix led to a reboot loop, and magisk just wont work  
  
TODO:
automatic unpack boot & get kernel file  ✔️  
automatic patch kernel  ✔️  
automatic repack boot  ✔️  
  
new feature: auto detect linux kernel major version and will notice user when the major version is not 4.  
new feature: auto decompress kernel when the kernel file is compressed.  
new feature: make the mount fix optional.  
  
fix: some temp files won't be deleted after the program exited unexpectly.  
fix: custom save path feature does nothing.  
fix: can't read linux kernel version correctly.  
fix: translation errors.  
  
p.s. this tool itself's development was finished. ~~now we're working on fix some selinux policies for **_some certain models_** to get magisk work.~~ and **plz notice that this tool won't fix problems caused by selinux and other non-kernel stuff, it only patches the kernel and that's all.**  

p.s. okay i gave up. ~fxxk vivo~ on some models there're restrictions not only in the kernel but in /vendor and somewhere else. and i still can't get magiskd work or get post-fs-data running at boot. i'm pretty sure that on **_some certain models_** u can't get magisk work normally by just patch the kernel. ~but magisk suu works perfectly holy sh*t~ if this patch didn't work for u, u can go back and use magisk suu instead.  

_~fxxk u vivo fxxk u bbk look at what u've done!~_  
