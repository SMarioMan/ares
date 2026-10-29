// Experimental, deterministic frame worker. The transport lives in session.py.
#include <ares/ares.hpp>
#include <sfc/sfc.hpp>
#include <mia/mia.hpp>
#include <nall/main.hpp>
#include <array>
#include <bit>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <fstream>
#include <mutex>
#include <optional>
#include <SDL3/SDL.h>

namespace sfc = ares::SuperFamicom;

struct Worker : ares::Platform {
  ares::Node::System root;
  std::shared_ptr<mia::Pak> game, system;
  std::array<uint16_t, 8> pads{};
  std::array<uint8_t, 8> characters{0,1,2,3,4,5,6,7};
  std::array<uint8_t, 8192> linkRAM{};
  bool linkedROM = false;
  uint32_t frame = 0;
  std::mutex imageMutex;
  std::vector<uint32_t> image;
  unsigned imageWidth=0, imageHeight=0;
  unsigned displayWidth=0, displayHeight=0;
  SDL_Window* window=nullptr;
  SDL_Renderer* renderer=nullptr;
  SDL_Texture* texture=nullptr;
  SDL_Gamepad* gamepad=nullptr;
  SDL_AudioStream* audioStream=nullptr;
  unsigned textureWidth=0, textureHeight=0, localSlot=0;
  int gamepadIndex=0;
  bool keyboardEnabled=true, assignedInput=false, audioOutputEnabled=true;
  bool quitting=false, presentationOnly=false;
  bool localView=false;
  bool fastPresentation=true;
  bool externalView=false, raceViewActive=false;
  uint64_t viewEpoch=0;
  unsigned viewCourse=255, viewRound=255, viewTarget=255, externalWidth=0, externalHeight=0;
  uint32_t externalFrame=0;
  std::vector<uint32_t> externalImage;
  std::optional<serializer> canonicalState;
  unsigned snapshotSize=0;
  double frameRate=60.0;
  uint8_t selectedCourse=255;
  uint64_t audioFrames=0, audioSignature=14695981039346656037ull;

  ~Worker() {
    sfc::PPUBase::objectColor={};
    if(root) root->unload();
    if(audioStream) SDL_DestroyAudioStream(audioStream);
    if(gamepad) SDL_CloseGamepad(gamepad);
    if(texture) SDL_DestroyTexture(texture);
    if(renderer) SDL_DestroyRenderer(renderer);
    if(window) SDL_DestroyWindow(window);
    if(window) SDL_Quit();
  }

  auto openWindow(unsigned slot) -> void {
    localSlot=slot;
    localView=true;
    SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS,"1");
    if(!SDL_Init(SDL_INIT_VIDEO|SDL_INIT_AUDIO|SDL_INIT_GAMEPAD))
      throw std::runtime_error(SDL_GetError());
    std::string title="Super Mario Kart Link — Player "+std::to_string(slot+1);
    if(!SDL_CreateWindowAndRenderer(title.c_str(), 1024, 896, SDL_WINDOW_RESIZABLE, &window, &renderer))
      throw std::runtime_error(SDL_GetError());
    SDL_SetRenderVSync(renderer, 0);
    int count=0;
    auto ids=SDL_GetGamepads(&count);
    if(gamepadIndex>=0 && gamepadIndex<count) gamepad=SDL_OpenGamepad(ids[gamepadIndex]);
    SDL_free(ids);
    SDL_AudioSpec spec{SDL_AUDIO_F32, 2, 48000};
    audioStream=SDL_OpenAudioDeviceStream(SDL_AUDIO_DEVICE_DEFAULT_PLAYBACK, &spec, nullptr, nullptr);
    if(audioStream) SDL_ResumeAudioStreamDevice(audioStream);
  }
  auto pollInput() -> uint16_t {
    SDL_Event event;
    while(SDL_PollEvent(&event)) {
      if(event.type==SDL_EVENT_QUIT) quitting=true;
      if(event.type==SDL_EVENT_GAMEPAD_REMOVED && gamepad && SDL_GetGamepadID(gamepad)==event.gdevice.which) {
        if(assignedInput) quitting=true;
        SDL_CloseGamepad(gamepad); gamepad=nullptr;
      }
      if(event.type==SDL_EVENT_GAMEPAD_ADDED && !gamepad && gamepadIndex>=0) {
        int count=0; auto ids=SDL_GetGamepads(&count);
        if(gamepadIndex<count) gamepad=SDL_OpenGamepad(ids[gamepadIndex]);
        SDL_free(ids);
      }
    }
    auto keys=SDL_GetKeyboardState(nullptr);
    const SDL_Scancode codes[]={SDL_SCANCODE_Z,SDL_SCANCODE_A,SDL_SCANCODE_BACKSPACE,SDL_SCANCODE_RETURN,
      SDL_SCANCODE_UP,SDL_SCANCODE_DOWN,SDL_SCANCODE_LEFT,SDL_SCANCODE_RIGHT,
      SDL_SCANCODE_X,SDL_SCANCODE_S,SDL_SCANCODE_Q,SDL_SCANCODE_W};
    const SDL_GamepadButton buttons[]={SDL_GAMEPAD_BUTTON_SOUTH,SDL_GAMEPAD_BUTTON_WEST,SDL_GAMEPAD_BUTTON_BACK,
      SDL_GAMEPAD_BUTTON_START,SDL_GAMEPAD_BUTTON_DPAD_UP,SDL_GAMEPAD_BUTTON_DPAD_DOWN,
      SDL_GAMEPAD_BUTTON_DPAD_LEFT,SDL_GAMEPAD_BUTTON_DPAD_RIGHT,SDL_GAMEPAD_BUTTON_EAST,
      SDL_GAMEPAD_BUTTON_NORTH,SDL_GAMEPAD_BUTTON_LEFT_SHOULDER,SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER};
    uint16_t result=0;
    for(unsigned i=0;i<12;++i)
      if((keyboardEnabled && keys[codes[i]]) || (gamepad && SDL_GetGamepadButton(gamepad,buttons[i]))) result|=1u<<(15-i);
    if(gamepad) {
      auto x=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTX),y=SDL_GetGamepadAxis(gamepad,SDL_GAMEPAD_AXIS_LEFTY);
      if(x < -16000) result|=0x0200;
      if(x > 16000) result|=0x0100;
      if(y < -16000) result|=0x0800;
      if(y > 16000) result|=0x0400;
    }
    if(SDL_GetWindowFlags(window)&SDL_WINDOW_INPUT_FOCUS && keys[SDL_SCANCODE_ESCAPE]) quitting=true;
    if((result&0x0c00)==0x0c00) result&=~0x0c00;
    if((result&0x0300)==0x0300) result&=~0x0300;
    return result;
  }
  auto present() -> void {
    if(!renderer) return;
    std::lock_guard lock(imageMutex);
    bool privateImage=externalView && raceViewActive;
    if(privateImage && externalImage.empty()) return;
    unsigned width=privateImage ? externalWidth : imageWidth;
    unsigned height=privateImage ? externalHeight : imageHeight;
    const auto& pixels=privateImage ? externalImage : image;
    if(!width || !height) return;
    if(width!=textureWidth || height!=textureHeight) {
      if(texture) SDL_DestroyTexture(texture);
      texture=SDL_CreateTexture(renderer, SDL_PIXELFORMAT_ARGB8888, SDL_TEXTUREACCESS_STREAMING,width,height);
      if(!texture) throw std::runtime_error(SDL_GetError());
      textureWidth=width; textureHeight=height;
      SDL_SetTextureScaleMode(texture,SDL_SCALEMODE_NEAREST);
    }
    // SNES output can contain doubled horizontal samples. Honor the core's
    // sample scale and pixel aspect just as the desktop frontend does.
    SDL_SetRenderLogicalPresentation(renderer,displayWidth,displayHeight,SDL_LOGICAL_PRESENTATION_LETTERBOX);
    SDL_UpdateTexture(texture,nullptr,pixels.data(),width*sizeof(uint32_t));
    SDL_RenderClear(renderer);
    SDL_RenderTexture(renderer,texture,nullptr,nullptr);
    SDL_RenderPresent(renderer);
  }
  auto refreshRateHint(double rate) -> void override { frameRate=rate; }
  auto cameraSlot() const -> unsigned {
    if(linkRAM[0x3b3] && linkRAM[0xcb2] && !linkRAM[0xc10+localSlot*2]) {
      for(unsigned slot=0;slot<linkRAM[0x3b2];++slot) if(linkRAM[0xc10+slot*2]) return slot;
    }
    return localSlot;
  }
  auto updateTitle() -> void {
    if(!window) return;
    std::string title="Super Mario Kart Link — Player "+std::to_string(localSlot+1)+" of "+std::to_string(linkRAM[0x3b2]);
    if(linkRAM[0x3b3]) {
      title+=" — Battle";
      if(linkRAM[0xcb2]) {
        if(linkRAM[0xcb4]) {
          unsigned winner=linkRAM[0xcb0] | unsigned(linkRAM[0xcb1])<<8;
          title+=winner<8 ? " — Player "+std::to_string(winner+1)+" wins" : " — Draw";
        } else if(!linkRAM[0xc10+localSlot*2]) {
          title+=" — Out; watching Player "+std::to_string(cameraSlot()+1);
        }
      }
    }
    if(title!=SDL_GetWindowTitle(window)) SDL_SetWindowTitle(window,title.c_str());
  }
  auto localRaceActive() const -> bool {
    // Pause and the completed-race/results sequence use the shared host UI.
    return linkedROM && (sfc::cpu.wram[0x36]==2 || (linkRAM[0x3b3] && sfc::cpu.wram[0x36]==14 && !linkRAM[0xcb4])) && sfc::cpu.wram[0x3a]>=6
      && !(sfc::cpu.wram[0x163]&0x80) && sfc::cpu.wram[0x144]<16;
  }
  auto updateViewEpoch() -> void {
    bool active=frame && localRaceActive();
    unsigned course=sfc::cpu.wram[0x124], round=sfc::cpu.wram[0x152],target=cameraSlot();
    if(active!=raceViewActive || (active && (course!=viewCourse || round!=viewRound || target!=viewTarget))) {
      ++viewEpoch;
      externalImage.clear();
      externalFrame=0;
    }
    raceViewActive=active; viewCourse=course; viewRound=round; viewTarget=target;
  }
  auto importImage(uint32_t sourceFrame, uint64_t epoch, const std::string& path) -> bool {
    if(!externalView || !raceViewActive || epoch!=viewEpoch || sourceFrame>frame || sourceFrame<externalFrame) return false;
    std::ifstream input(path,std::ios::binary);
    std::string magic;
    unsigned width=0,height=0,maximum=0;
    if(!(input>>magic>>width>>height>>maximum) || magic!="P6" || !width || !height || width>1024 || height>1024 || maximum!=255 || input.get()!='\n')
      throw std::runtime_error("Invalid private image header");
    std::vector<uint8_t> rgb(width*height*3);
    if(!input.read(reinterpret_cast<char*>(rgb.data()),rgb.size()) || input.peek()!=std::char_traits<char>::eof())
      throw std::runtime_error("Invalid private image size");
    std::lock_guard lock(imageMutex);
    externalImage.resize(width*height);
    for(unsigned i=0;i<width*height;++i)
      externalImage[i]=0xff000000u | (uint32_t(rgb[i*3])<<16) | (uint32_t(rgb[i*3+1])<<8) | rgb[i*3+2];
    externalWidth=width; externalHeight=height; externalFrame=sourceFrame;
    return true;
  }

  auto pak(ares::Node::Object node) -> std::shared_ptr<vfs::directory> override {
    if(node->name() == "Super Famicom") return system->pak;
    if(node->name() == "Super Famicom Cartridge") return game->pak;
    return {};
  }
  auto audio(ares::Node::Audio::Stream stream) -> void override {
    double samples[16];
    while(stream->pending()) {
      auto channels=stream->read(samples);
      if(!presentationOnly) {
        ++audioFrames;
        for(unsigned c=0;c<channels;++c)
          audioSignature=(audioSignature^std::bit_cast<uint64_t>(samples[c]))*1099511628211ull;
      }
      if(audioStream && audioOutputEnabled && !presentationOnly && SDL_GetAudioStreamQueued(audioStream)<262144) {
        float converted[16];
        for(unsigned c=0;c<channels;++c) converted[c]=samples[c];
        SDL_PutAudioStreamData(audioStream,converted,channels*sizeof(float));
      }
    }
  }
  auto video(ares::Node::Video::Screen screen, const u32* data, u32 pitch, u32 width, u32 height) -> void override {
    std::lock_guard lock(imageMutex);
    imageWidth=width; imageHeight=height;
    displayWidth=width*screen->scaleX()*screen->aspectX()/screen->aspectY();
    displayHeight=height*screen->scaleY();
    image.resize(width*height);
    for(unsigned y=0;y<height;++y)
      std::copy_n(reinterpret_cast<const uint32_t*>(reinterpret_cast<const uint8_t*>(data)+y*pitch), width, image.data()+y*width);
  }
  auto waitForVideo() -> void {
    for(auto screen : ares::Node::enumerate<ares::Node::Video::Screen>(root)) screen->waitForFrame();
  }
  auto renderLocal() -> void {
    if(!localView || !localRaceActive()) return;
    // Follow Ares's run-ahead save/restore path. The speculative frame is never
    // committed to the canonical world, and its audio is discarded.
    auto saved=root->serialize(false);
    auto writeWord=[](unsigned address,unsigned value) {
      sfc::cpu.wram[address]=value; sfc::cpu.wram[address+1]=value>>8;
    };
    unsigned viewSlot=cameraSlot();
    unsigned racer=0x1000+viewSlot*256;
    if(viewSlot) {
      // The native foreground kart is drawn through player 1's object script.
      // Exchange semantic racer data while retaining each object's intrusive
      // list links and script pointers; remap rank pointers in this private view.
      auto readWord=[](unsigned address) { return unsigned(sfc::cpu.wram[address]) | (unsigned(sfc::cpu.wram[address+1])<<8); };
      unsigned hostTiles=readWord(0x1014),guestTiles=readWord(racer+0x14);
      writeWord(0x1014,(hostTiles&0x01ff) | (guestTiles&0xfe00));
      writeWord(racer+0x14,(guestTiles&0x01ff) | (hostTiles&0xfe00));
      for(unsigned offset=0x10;offset<0x100;++offset) {
        // Preserve object-local graphics storage, animation interpreter and
        // viewport assignment while exchanging the kart's simulation fields.
        if(offset==0x14 || offset==0x15 || (offset>=0x42 && offset<=0x4f)
          || (offset>=0xb6 && offset<=0xb9) || offset==0xd2 || offset==0xd3) continue;
        std::swap(sfc::cpu.wram[0x1000+offset],sfc::cpu.wram[racer+offset]);
      }
      for(unsigned table : {0x10e,0xf70}) for(unsigned i=0;i<8;++i) {
        unsigned address=table+i*2;
        unsigned target=unsigned(sfc::cpu.wram[address]) | (unsigned(sfc::cpu.wram[address+1])<<8);
        if(target==0x1000) writeWord(address,racer);
        else if(target==racer) writeWord(address,0x1000);
      }
    }
    racer=0x1000;
    // Depth caches belong to the previous camera. Native culling otherwise
    // skips reprojecting an off-camera kart forever during a frozen render pass.
    for(unsigned slot=0;slot<8;++slot) {
      writeWord(0x1006 + slot*256,0);
      writeWord(0x100e + slot*256,0);
    }
    auto savedLink=linkRAM;
    for(unsigned offset=0;offset<0x80;++offset)
      linkRAM[0x800+offset]=savedLink[0x800+viewSlot*0x80+offset];
    linkRAM[0x80e]=0x00; linkRAM[0x80f]=0x10;
    linkRAM[0x7a0]=savedLink[0x7a0+viewSlot*2];
    linkRAM[0x7a1]=savedLink[0x7a1+viewSlot*2];
    if(viewSlot) {
      for(unsigned base : {0x440,0x500,0x520,0x540,0x560,0x580}) {
        linkRAM[base]=linkRAM[base+viewSlot*2];
        linkRAM[base+1]=linkRAM[base+viewSlot*2+1];
      }
    }
    // Freeze HUD values from the source snapshot. A resumed core can finish a
    // partially executed native item script before reaching the presentation
    // gate; those speculative changes must not shift the displayed blink phase.
    for(unsigned byte=0;byte<2;++byte) {
      linkRAM[0x7e4+byte]=savedLink[0x500+viewSlot*2+byte];
      linkRAM[0x7e6+byte]=savedLink[0x540+viewSlot*2+byte];
    }
    linkRAM[0xcd0]=linkRAM[0x3b3] && viewSlot && !savedLink[0xc10];
    linkRAM[0xcd1]=0;
    if(linkRAM[0x3b3] && viewSlot) {
      for(unsigned slot=0;slot<linkRAM[0x3b2];++slot) for(unsigned balloon=0;balloon<3;++balloon) {
        unsigned address=0x1000+slot*0x180+balloon*0x80+0x70;
        unsigned owner=linkRAM[address] | unsigned(linkRAM[address+1])<<8;
        if(owner==0x1000) owner=0x1000+viewSlot*256;
        else if(owner==0x1000+viewSlot*256) owner=0x1000;
        linkRAM[address]=owner; linkRAM[address+1]=owner>>8;
      }
    }
    presentationOnly=true;
    linkRAM[0xcd8]=0; linkRAM[0xcd9]=0;
    for(auto stream : ares::Node::enumerate<ares::Node::Audio::Stream>(root)) stream->setDiscard(true);
    unsigned privateFrames=0;
    while(linkRAM[0xcd8]<3) {
      if(++privateFrames>48) {
        throw std::runtime_error("Private drawing did not complete");
      }
      writeWord(0xa8,racer);
      writeWord(0xc8,racer);
      writeWord(0xa4,0);
      writeWord(0xac,0xc0c0);  // Native active player follow-camera flags.
      writeWord(0xdc,0);
      auto kartWord=[&](unsigned offset) { return unsigned(sfc::cpu.wram[racer+offset]) | (unsigned(sfc::cpu.wram[racer+offset+1])<<8); };
      writeWord(0x88,(kartWord(0x18)<<2) | (kartWord(0x16)>>14));
      writeWord(0x8c,(kartWord(0x1c)<<2) | (kartWord(0x1a)>>14));
      writeWord(0x94,unsigned(sfc::cpu.wram[racer+0xa4]) | (unsigned(sfc::cpu.wram[racer+0xa5])<<8));
      // Skip intermediate rasterization until two complete native drawing
      // passes finish; battle scenes can span several video frames per pass.
      ares::setRunAhead(fastPresentation && linkRAM[0xcd8]<2);
      root->run();
      waitForVideo();
    }
    ares::setRunAhead(false);
    // Present the fully built OAM/VRAM buffers. The gate now waits without
    // starting another draw or clearing the completed foreground sprites.
    root->run();
    waitForVideo();
    saved.setReading();
    if(!root->unserialize(saved)) throw std::runtime_error("Cannot restore canonical world after presentation");
    linkRAM=savedLink;
    for(auto stream : ares::Node::enumerate<ares::Node::Audio::Stream>(root)) stream->setDiscard(false);
    presentationOnly=false;
  }
  auto input(ares::Node::Input::Input node) -> void override {
    auto button = node->cast<ares::Node::Input::Button>();
    if(!button) return;
    const char* names[] = {"B", "Y", "Select", "Start", "Up", "Down", "Left", "Right", "A", "X", "L", "R"};
    auto port = node->parent().lock()->parent().lock();
    unsigned slot = port->name() == "Controller Port 2" ? 1 : 0;
    button->setValue(false);
    for(unsigned i = 0; i < 12; ++i) {
      bool reservedSelection=linkedROM && sfc::cpu.wram[0x36]==6 && i>=4 && i<=7;
      bool battleCharacter=linkedROM && linkRAM[0x3b3] && sfc::cpu.wram[0x36]==6;
      bool hostConfirmed=battleCharacter && (sfc::cpu.wram[0x70]&3)==2;
      // Both native battle result panels wait for their own controller. The
      // linked session has one menu owner, including when player 1 won.
      bool battleResult=linkedROM && linkRAM[0x3b3] && linkRAM[0xcb4] && sfc::cpu.wram[0x36]==14;
      bool battleConfirm=slot && ((hostConfirmed && (i==0 || i==8))
        || (battleResult && (i==0 || i==3 || i==8)));
      if(node->name() == names[i]) button->setValue((pads[battleConfirm ? 0 : slot] >> (15-i)) & 1
        && (!(linkedROM && slot) || battleConfirm) && !reservedSelection
        && !(hostConfirmed && !slot && (i==0 || i==8)));
    }
  }
  // Live and atomically latched inputs. The ROM strobes once per world update,
  // so an update spanning video frames cannot mix different input bundles.
  auto readLink(n24 address, n8 openBus) -> n8 {
    unsigned offset = address & 0x3f;
    if(offset < 16) return pads[offset/2] >> (8*(offset&1));
    if(offset >= 16 && offset < 20) return "LNK1"[offset-16];
    if(offset == 20) return 8;
    if(offset == 21) return presentationOnly;
    if(offset == 22) return selectedCourse;
    if(offset == 23) return linkRAM[0x3b2];
    if(offset == 29) return linkRAM[0x3b3];
    if(offset >= 24 && offset < 28) return frame >> (8*(offset-24));
    if(offset >= 32 && offset < 48) return linkRAM[0x3a0+offset-32];
    if(offset >= 48 && offset < 56) return characters[offset-48];
    return openBus;
  }
  auto writeLink(n24 address, n8) -> void {
    if((address & 0x3f)!=28) return;
    for(unsigned slot=0;slot<8;++slot) {
      linkRAM[0x3a0+slot*2]=pads[slot];
      linkRAM[0x3a1+slot*2]=pads[slot]>>8;
    }
  }
  auto snapshot() -> serializer {
    // Synchronize all coprocessors before hashing a portable serialized state.
    auto state = root->serialize(true);
    state(frame);
    for(auto& pad : pads) state(pad);
    for(auto& character : characters) state(character);
    state(selectedCourse);
    for(auto& byte : linkRAM) state(byte);
    return state;
  }
  auto digest() -> std::string {
    auto state = snapshot();
    snapshotSize=state.size();
    std::string result=Hash::SHA256({state.data(), state.size()}).digest().data();
    canonicalState=std::move(state);
    return result;
  }
  auto load(const char* path) -> void {
    linkRAM[0x3b2]=8;
    auto rom = file::read(path);
    linkedROM = rom.size() > 0xffd5 && memory::compare(rom.data()+0xffc0, "SUPER MARIO KART LINK", 21) == 0;
    ares::platform = this;
    mia::setHomeLocation([] { return string{Path::userData(), "ares/link/"}; });
    game = mia::Medium::create("Super Famicom");
    system = mia::System::create("Super Famicom");
    if(game->load(path) != successful || system->load() != successful)
      throw std::runtime_error("Cannot load ROM or Super Famicom board database");
    sfc::option("Deterministic Entropy", "true");
    sfc::option("Pixel Accuracy", "false");
    if(!sfc::load(root, "[Nintendo] Super Famicom (NTSC)"))
      throw std::runtime_error("Cannot load SNES core");
    auto cart = root->find<ares::Node::Port>("Cartridge Slot");
    cart->allocate(); cart->connect();
    for(auto name : {"Controller Port 1", "Controller Port 2"}) {
      auto port = root->find<ares::Node::Port>(name);
      port->allocate("Gamepad"); port->connect();
    }
    root->power();
    sfc::PPUBase::objectColor=[this](n9 tile,n3 palette,n4 index,n15 native) -> n15 {
      if(!linkedROM || !linkRAM[0x3b3] || sfc::cpu.wram[0x36]!=14 || tile<0x120 || tile>0x13c) return native;
      // DS-style slot colors in SNES RGB555. Separate OBJ palettes preserve
      // native kart/item CGRAM, shading, highlights, transparency and color math.
      static constexpr unsigned colors[8][2]={
        {0x7e00,0x7000}, {0x001f,0x0014}, {0x1360,0x0a40}, {0x039f,0x0214},
        {0x74b5,0x482d}, {0x7f80,0x4e60}, {0x01df,0x00f5}, {0x5d9f,0x3c96}
      };
      if(index==12) return colors[palette][0];
      if(index==13) return colors[palette][1];
      if(index==15) return 0x7fff;
      return native;
    };
    sfc::bus.map([this](n24 a, n8 d) { return readLink(a, d); },
      [this](n24 a, n8 d) { writeLink(a, d); }, "00-3f,80-bf:21c0-21ff");
    if(linkedROM) {
      sfc::bus.map([this](n24 a, n8) -> n8 { return linkRAM[a & 4095]; },
        [this](n24 a, n8 d) { linkRAM[a & 4095] = d; }, "00-0f,80-8f:3000-3fff");
      sfc::bus.map([this](n24 a, n8) -> n8 { return linkRAM[0x1000+(a & 4095)]; },
        [this](n24 a, n8 d) { linkRAM[0x1000+(a & 4095)] = d; }, "00-0f,80-8f:5000-5fff");
    }
  }
};

auto nall::main(Arguments arguments) -> void {
  bool interactive=arguments.size()==3 && arguments[0]=="--window";
  unsigned localSlot=0;
  if(interactive) {
    arguments.take(); localSlot=arguments.take().natural();
    if(localSlot>=8) throw std::runtime_error("Invalid local player slot");
  }
  bool probe = arguments.size() == 2 && arguments[0] == "--verify-link-probe";
  if(probe) arguments.take();
  if(arguments.size() != 1) { std::cerr << "Usage: ares-link-worker [--verify-link-probe] ROM.sfc\n"; std::exit(2); }
  try {
    Worker worker;
    worker.load(arguments[0].data());
    if(interactive) worker.openWindow(localSlot);
    std::cout << worker.digest() << std::endl;
    std::string line;
    std::array<uint16_t,8> probePrevious{};
    while(std::getline(std::cin, line)) {
      if(line=="@rate") {
        std::cout.precision(17);
        std::cout << worker.frameRate << std::endl;
        continue;
      }
      if(line.starts_with("@external-view ")) {
        auto slot=std::stoul(line.substr(15));
        if(slot>=8) throw std::runtime_error("Invalid external view slot");
        worker.localSlot=slot; worker.localView=false; worker.externalView=true;
        worker.externalImage.clear(); worker.updateViewEpoch();
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@export ")) {
        worker.updateViewEpoch();
        if(!worker.raceViewActive) { std::cout << "skip" << std::endl; continue; }
        if(!worker.canonicalState) throw std::runtime_error("No canonical state available for presentation");
        auto& state=*worker.canonicalState;
        if(!file::write(line.substr(8).c_str(),{state.data(),state.size()})) throw std::runtime_error("Cannot export canonical presentation state");
        std::cout << worker.frame << " " << worker.viewEpoch << std::endl;
        continue;
      }
      if(line.starts_with("@import-image ")) {
        std::istringstream values(line.substr(14));
        uint32_t sourceFrame;
        uint64_t epoch;
        std::string path;
        if(!(values>>sourceFrame>>epoch>>std::ws) || !std::getline(values,path)) throw std::runtime_error("Invalid private image command");
        bool accepted=worker.importImage(sourceFrame,epoch,path);
        if(accepted) worker.present();
        std::cout << (accepted ? "ok" : "skip") << std::endl;
        continue;
      }
      if(line=="@draw") {
        worker.waitForVideo(); worker.renderLocal();
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@audio-output ")) {
        auto enabled=line.substr(14);
        if(enabled!="0" && enabled!="1") throw std::runtime_error("Invalid audio output setting");
        worker.audioOutputEnabled=enabled=="1";
        if(worker.audioStream) SDL_ClearAudioStream(worker.audioStream);
        std::cout << "ok" << std::endl; continue;
      }
      if(line=="@state") { std::cout << worker.digest() << std::endl; continue; }
      if(line=="@focus") {
        if(!worker.window) throw std::runtime_error("No game window");
        SDL_RaiseWindow(worker.window); std::cout << "ok" << std::endl; continue;
      }
      if(line.starts_with("@tile ")) {
        unsigned column,row,columns,rows; std::istringstream values(line.substr(6));
        if(!worker.window || !(values>>column>>row>>columns>>rows) || !columns || !rows || columns>8 || rows>8 || column>=columns || row>=rows)
          throw std::runtime_error("Invalid window layout");
        SDL_Rect area;
        if(!SDL_GetDisplayUsableBounds(SDL_GetDisplayForWindow(worker.window),&area)) throw std::runtime_error(SDL_GetError());
        int width=std::max(256,area.w/int(columns)),height=std::max(224,area.h/int(rows));
        SDL_SetWindowSize(worker.window,width,height);
        SDL_SetWindowPosition(worker.window,area.x+column*width,area.y+row*height);
        std::cout << "ok" << std::endl; continue;
      }
      if(line.starts_with("@input ")) {
        int index=0,keyboard=0; std::istringstream values(line.substr(7));
        if(!worker.window || !(values>>index>>keyboard) || index< -1 || index>7 || (keyboard!=0 && keyboard!=1))
          throw std::runtime_error("Invalid local input assignment");
        if(worker.gamepad) SDL_CloseGamepad(worker.gamepad);
        worker.gamepad=nullptr; worker.gamepadIndex=index; worker.keyboardEnabled=keyboard; worker.assignedInput=true;
        int count=0; auto ids=SDL_GetGamepads(&count);
        if(index>=0 && index<count) worker.gamepad=SDL_OpenGamepad(ids[index]);
        SDL_free(ids);
        std::cout << "ok" << std::endl; continue;
      }
      if(line.starts_with("@mode ")) {
        auto mode=line.substr(6);
        if(worker.frame || (mode!="grand-prix" && mode!="battle")) throw std::runtime_error("Invalid or late game mode");
        worker.linkRAM[0x3b3]=mode=="battle";
        std::cout << worker.digest() << std::endl; continue;
      }
      if(line.starts_with("@players ")) {
        auto count=std::stoul(line.substr(9));
        if(worker.frame || count<2 || count>8) throw std::runtime_error("Invalid or late player count");
        worker.linkRAM[0x3b2]=count;
        if(worker.window) {
          std::string title="Super Mario Kart Link — Player "+std::to_string(worker.localSlot+1)+" of "+std::to_string(count);
          SDL_SetWindowTitle(worker.window,title.c_str());
        }
        std::cout << worker.digest() << std::endl;
        continue;
      }
      if(line=="@render-full") {
        worker.fastPresentation=false;
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line=="@display") {
        std::lock_guard lock(worker.imageMutex);
        std::cout << worker.displayWidth << " " << worker.displayHeight << std::endl;
        continue;
      }
      if(line=="@audio") {
        std::cout << worker.audioFrames << " " << std::hex << worker.audioSignature << std::dec << std::endl;
        continue;
      }
      if(line.starts_with("@course ")) {
        auto course=std::stoul(line.substr(8));
        if(worker.frame || (course!=255 && (worker.linkRAM[0x3b3] ? (course<20 || course>=24) : course>=20))) throw std::runtime_error("Invalid or late course selection");
        worker.selectedCourse=course;
        std::cout << worker.digest() << std::endl;
        continue;
      }
      if(line.starts_with("@linkword ")) {
        worker.canonicalState.reset();
        std::istringstream values(line.substr(10));
        unsigned offset,value;
        if(!(values>>std::hex>>offset>>value) || offset>=worker.linkRAM.size()-1 || value>65535)
          throw std::runtime_error("Invalid diagnostic link word");
        worker.linkRAM[offset]=value; worker.linkRAM[offset+1]=value>>8;
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@word ")) {
        worker.canonicalState.reset();
        std::istringstream values(line.substr(6));
        unsigned offset,value;
        if(!(values>>std::hex>>offset>>value) || offset>=131071 || value>65535)
          throw std::runtime_error("Invalid diagnostic WRAM word");
        sfc::cpu.wram[offset]=value; sfc::cpu.wram[offset+1]=value>>8;
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@linkpeek ")) {
        std::istringstream values(line.substr(10));
        unsigned offset,length;
        if(!(values>>std::hex>>offset>>length) || offset>=worker.linkRAM.size() || length>worker.linkRAM.size()-offset)
          throw std::runtime_error("Invalid diagnostic link range");
        static constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0;i<length;++i) {
          auto value=worker.linkRAM[offset+i]; std::cout << hex[value>>4] << hex[value&15];
        }
        std::cout << std::endl;
        continue;
      }
      if(line.starts_with("@graphics ")) {
        std::istringstream values(line.substr(10));
        std::string memory; unsigned offset,length;
        if(!(values>>memory>>std::hex>>offset>>length) || (memory!="cgram" && memory!="vram")
          || offset>=(memory=="cgram" ? 512u : 65536u) || length>(memory=="cgram" ? 512u : 65536u)-offset)
          throw std::runtime_error("Invalid diagnostic graphics range");
        static constexpr char hex[]="0123456789abcdef";
        ares::Node::Debugger::Memory source;
        for(auto node : ares::Node::enumerate<ares::Node::Debugger::Memory>(worker.root))
          if(node->name()==(memory=="cgram" ? "PPU CGRAM" : "PPU VRAM")) source=node;
        if(!source) throw std::runtime_error("Graphics memory is unavailable");
        for(unsigned i=offset;i<offset+length;++i) {
          unsigned byte=source->read(i);
          std::cout << hex[byte>>4] << hex[byte&15];
        }
        std::cout << std::endl;
        continue;
      }
      if(line.starts_with("@buspeek ")) {
        std::istringstream values(line.substr(9)); unsigned address,length;
        if(!(values>>std::hex>>address>>length) || address>=0x1000000 || length>4096 || length>0x1000000-address)
          throw std::runtime_error("Invalid diagnostic bus range");
        static constexpr char hex[]="0123456789abcdef";
        for(unsigned i=0;i<length;++i) {
          unsigned byte=sfc::bus.read(address+i,0); std::cout<<hex[byte>>4]<<hex[byte&15];
        }
        std::cout<<std::endl; continue;
      }
      if(line.starts_with("@view ")) {
        auto slot=std::stoul(line.substr(6));
        if(slot>=8) throw std::runtime_error("Invalid presentation slot");
        worker.localSlot=slot; worker.localView=true;
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line=="@poll") {
        auto pad=worker.pollInput();
        if(worker.quitting) std::cout << "quit" << std::endl;
        else std::cout << std::hex << pad << std::dec << std::endl;
        continue;
      }
      if(line.starts_with("@characters ")) {
        if(worker.frame) throw std::runtime_error("Roster is immutable after power-on");
        std::istringstream values(line.substr(12));
        unsigned used=0, character;
        for(auto& c:worker.characters) {
          if(!(values>>character) || character>=8 || (used & (1u<<character)))
            throw std::runtime_error("Invalid or duplicate character");
          used|=1u<<character; c=character;
        }
        std::cout << worker.digest() << std::endl;
        continue;
      }
      if(line.starts_with("@save ")) {
        worker.canonicalState.reset();
        auto state = worker.snapshot();
        if(!file::write(line.substr(6).c_str(), {state.data(), state.size()}))
          throw std::runtime_error("Cannot save diagnostic snapshot");
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@load ")) {
        worker.canonicalState.reset();
        auto bytes = file::read(line.substr(6).c_str());
        if(bytes.size()!=worker.snapshotSize) throw std::runtime_error("Snapshot size does not match this cartridge/build");
        serializer state(bytes.data(), bytes.size());
        if(!worker.root->unserialize(state)) throw std::runtime_error("Cannot restore diagnostic snapshot");
        state(worker.frame);
        for(auto& pad : worker.pads) state(pad);
        for(auto& character : worker.characters) state(character);
        state(worker.selectedCourse);
        for(auto& byte : worker.linkRAM) state(byte);
        std::cout << "ok" << std::endl;
        continue;
      }
      if(line.starts_with("@image ")) {
        std::lock_guard lock(worker.imageMutex);
        std::ofstream output(line.substr(7), std::ios::binary);
        bool external=worker.externalView && worker.raceViewActive && !worker.externalImage.empty();
        output << "P6\n" << (external ? worker.externalWidth : worker.imageWidth) << " "
          << (external ? worker.externalHeight : worker.imageHeight) << "\n255\n";
        for(auto pixel: external ? worker.externalImage : worker.image) {
          output.put(pixel>>16); output.put(pixel>>8); output.put(pixel);
        }
        output.close();  // The acknowledgement must follow the final disk flush.
        std::cout << (output.good() ? "ok" : "failed") << std::endl;
        continue;
      }
      if(line == "@info") {
        std::cout << "pc=" << std::hex << unsigned(sfc::cpu.r.pc.d) << " db=" << unsigned(sfc::cpu.r.b)
          << " sp=" << unsigned(sfc::cpu.r.s.w) << " linked=" << worker.linkedROM << std::dec << std::endl;
        std::cerr << worker.game->manifest << std::endl;
        continue;
      }
      if(line.starts_with("@peek ")) {
        std::istringstream command(line.substr(6));
        unsigned address, length;
        if(!(command >> std::hex >> address >> length) || address >= 131072 || length > 131072-address)
          throw std::runtime_error("Invalid WRAM inspection range");
        static constexpr char hex[] = "0123456789abcdef";
        for(unsigned i = 0; i < length; ++i) {
          unsigned value = sfc::cpu.wram[address+i];
          std::cout << hex[value>>4] << hex[value&15];
        }
        std::cout << std::endl;
        continue;
      }
      std::istringstream input(line);
      unsigned value;
      for(auto& pad : worker.pads) {
        if(!(input >> std::hex >> value) || value > 0xffff || (value & 0xf))
          throw std::runtime_error("Expected eight SNES button words with low nibble zero");
        pad = value;
      }
      if(input >> line) throw std::runtime_error("Too many button words");
      if(probe) for(unsigned i=0;i<8;++i) {
        uint16_t latched=worker.readLink(0x21e0+i*2,0) | (unsigned(worker.readLink(0x21e1+i*2,0))<<8);
        if(latched!=probePrevious[i]) throw std::runtime_error("Input latch changed without a ROM strobe");
      }
      worker.root->run();
      worker.waitForVideo();
      ++worker.frame;
      auto digest = worker.digest();
      worker.waitForVideo();
      if(worker.externalView) worker.updateViewEpoch();
      worker.renderLocal();
      worker.updateTitle();
      worker.present();
      if(probe) {
        for(unsigned i = 0; i < 8; ++i) {
          uint16_t observed = sfc::cpu.wram[0x100+i*2] | (sfc::cpu.wram[0x101+i*2] << 8);
          if(observed != worker.pads[i])
            throw std::runtime_error("65816 link input probe mismatch at slot " + std::to_string(i));
          uint16_t latched=sfc::cpu.wram[0x120+i*2] | (sfc::cpu.wram[0x121+i*2]<<8);
          if(latched!=worker.pads[i]) throw std::runtime_error("65816 atomic input latch mismatch");
        }
        probePrevious=worker.pads;
      }
      std::cout << digest << std::endl;
    }
  } catch(const std::exception& error) {
    std::cerr << error.what() << '\n'; std::exit(1);
  }
}
